"""Adapters from versioned evaluation cases to existing medical services."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Mapping

from pydantic import ValidationError

from app.services.medical.ai.analyzer import MedicalInsightAnalyzer
from app.services.medical.ai.citation_validator import validate_citations
from app.services.medical.ai.context_builder import ContextBuilder
from app.services.medical.ai.exceptions import MedicalInsightError, MedicalInsightValidationError
from app.services.medical.ai.models import MedicalInsightReport
from app.services.medical.ai.question_templates import (
    QuestionTemplateError,
    normalize_question_suggestions,
)
from app.services.medical.ai.question_validator import validate_questions
from app.services.medical.ai.safety_validator import validate_safety
from app.services.medical.ai.support_validator import validate_support
from app.services.medical.evidence_matching.matcher import match_articles
from app.services.medical.evidence_matching.models import MatchableFinding
from app.services.medical.evaluation.models import EvaluationCase
from app.services.medical.literature.confirmation import confirm_literature_query
from app.services.medical.literature.exceptions import LiteratureQueryError
from app.services.medical.literature.models import LiteratureQuery
from app.services.medical.literature.query_builder import build_literature_query
from app.services.medical.terminology.models import ConceptSelection


class EvaluationAdapterError(ValueError):
    """Raised when a case input cannot be adapted to an existing service."""


class _RecordingPubMedProvider:
    """Record a released query without making a network request."""

    def __init__(self) -> None:
        self.calls: list[LiteratureQuery] = []

    async def search(self, query: LiteratureQuery) -> None:
        self.calls.append(query)


class _RecordingLiteratureBoundary:
    """Model the safe query-release boundary used by the API and worker.

    The evaluation remains offline: the provider is a recording fake, but a
    ready query still passes through run creation, queue, and provider stages.
    Blocked queries stop before all three stages.
    """

    def __init__(self) -> None:
        self.provider = _RecordingPubMedProvider()
        self.repository_create_count = 0
        self.queue_count = 0
        self.released_queries: list[str] = []

    def release(self, query: LiteratureQuery) -> None:
        """Record a release after the caller has passed production checks."""
        self.repository_create_count += 1
        self.queue_count += 1
        self.released_queries.append(query.normalized_query)
        asyncio.run(self.provider.search(query))


class _RecordingMedicalProvider:
    """Replay a case payload through MedicalInsightAnalyzer without a model."""

    name = "evaluation-fake"
    model_name = "evaluation-fake-v1"

    def __init__(self, payloads: list[Any]) -> None:
        self.payloads = list(payloads)
        self.calls: list[tuple[str, Any]] = []

    def generate(self, prompt: str, context: Any) -> Any:
        self.calls.append((prompt, context))
        if not self.payloads:
            raise RuntimeError("evaluation fake provider has no payload")
        return json.loads(json.dumps(self.payloads.pop(0)))


def evaluate_case(case: EvaluationCase, dataset_root: Path) -> dict[str, Any]:
    """Run one case against the corresponding production service boundary."""
    adapter = {
        "terminology": evaluate_terminology,
        "insight_safety": evaluate_insight_safety,
        "literature_matching": evaluate_literature_matching,
        "clinician_questions": evaluate_clinician_questions,
        "visit_preparation": evaluate_visit_preparation,
    }[case.suite]
    return adapter(case, dataset_root)


def evaluate_terminology(case: EvaluationCase, _dataset_root: Path) -> dict[str, Any]:
    """Exercise query preparation and release without contacting PubMed."""
    raw_selections = case.input.get("concept_selections", [])
    boundary = _RecordingLiteratureBoundary()
    try:
        selections = [ConceptSelection.model_validate(value) for value in raw_selections]
        query = build_literature_query(
            str(case.input.get("query") or ""),
            concept_selections=selections,
        )
    except LiteratureQueryError as exc:
        return {
            "resolution_status": "rejected",
            "external_query_allowed": False,
            "external_query_count": len(boundary.provider.calls),
            "repository_create_count": boundary.repository_create_count,
            "queue_count": boundary.queue_count,
            "provider_search_count": len(boundary.provider.calls),
            "released_queries": list(boundary.released_queries),
            "normalized_terms": [],
            "concept_ids": [],
            "normalized_query": "",
            "error_code": exc.code,
            "raw_fragments_in_query": [],
        }
    except ValidationError as exc:
        raise EvaluationAdapterError("invalid concept selection in terminology case") from exc

    try:
        # Reuse the production confirmation contract before entering the
        # recording repository/queue/provider boundary. The case controls
        # confirmation inputs so stale and missing consent are testable.
        confirm_literature_query(
            query,
            external_search_confirmed=bool(case.input.get("external_search_confirmed", False)),
            query_fingerprint=case.input.get("query_fingerprint"),
        )
    except LiteratureQueryError as exc:
        return _terminology_payload(query, boundary, case, error_code=exc.code)

    boundary.release(query)
    return _terminology_payload(query, boundary, case, error_code=None)


def _terminology_payload(
    query: LiteratureQuery,
    boundary: _RecordingLiteratureBoundary,
    case: EvaluationCase,
    *,
    error_code: str | None,
) -> dict[str, Any]:
    """Build stable terminology observations from the recording boundary."""
    normalized_query = query.normalized_query
    fragments = [str(value) for value in case.input.get("leak_checks", [])]
    released_query = "\n".join(boundary.released_queries)
    return {
        "resolution_status": query.resolution_status,
        "external_query_allowed": bool(boundary.provider.calls),
        "external_query_count": len(boundary.provider.calls),
        "repository_create_count": boundary.repository_create_count,
        "queue_count": boundary.queue_count,
        "provider_search_count": len(boundary.provider.calls),
        "released_queries": list(boundary.released_queries),
        "normalized_terms": [item.normalized for item in query.detected_concepts],
        "concept_ids": [item.concept_id for item in query.detected_concepts if item.concept_id],
        "normalized_query": normalized_query,
        "error_code": error_code,
        "raw_fragments_in_query": [
            value for value in fragments if value and value.casefold() in released_query.casefold()
        ],
    }


def evaluate_insight_safety(case: EvaluationCase, _dataset_root: Path) -> dict[str, Any]:
    """Run synthetic cases through the same analyzer path as production."""
    chunks = case.input.get("chunks", [])
    if not isinstance(chunks, list):
        raise EvaluationAdapterError("evaluation chunks must be a list")
    candidate = case.input.get("report", {})
    provider = _RecordingMedicalProvider(payloads=[candidate, candidate])
    analyzer = MedicalInsightAnalyzer(
        provider=provider,
        max_input_tokens=int(case.input.get("max_input_tokens", 12000)),
        redact_pii=True,
        schema_version="medical-insights-v3",
        prompt_version="medical-insights-v3",
    )
    try:
        output = analyzer.run(
            chunks,
            sections=(
                case.input.get("sections")
                if isinstance(case.input.get("sections"), list)
                else None
            ),
            source_warnings=(
                case.input.get("source_warnings")
                if isinstance(case.input.get("source_warnings"), list)
                else None
            ),
            title=str(case.input.get("title") or "Evaluation document"),
            document_kind=str(case.input.get("document_kind") or "research_paper"),
            language=str(case.input.get("language") or "en"),
        )
    except MedicalInsightValidationError as exc:
        return _insight_pipeline_failure(exc.errors, provider_call_count=len(provider.calls))
    except MedicalInsightError as exc:
        return {
            "pipeline_status": "rejected",
            "report_valid": False,
            "citation_valid": False,
            "support_valid": False,
            "safety_valid": False,
            "questions_valid": False,
            "error_codes": [exc.code],
            "validator_errors": [exc.code],
            "provider_call_count": len(provider.calls),
        }

    errors = [
        *output.citations.errors,
        *output.support.errors,
        *output.safety.errors,
        *output.questions.errors,
    ]
    return {
        "pipeline_status": "accepted",
        "report_valid": True,
        "citation_valid": output.citations.valid,
        "support_valid": output.support.valid,
        "safety_valid": output.safety.valid,
        "questions_valid": output.questions.valid,
        "citation_coverage": output.citations.coverage,
        "error_codes": _stable_error_codes(errors),
        "validator_errors": list(dict.fromkeys(errors)),
        "provider_call_count": len(provider.calls),
    }


def _insight_pipeline_failure(
    errors: list[str],
    *,
    provider_call_count: int,
) -> dict[str, Any]:
    """Expose which analyzer validation stage rejected a candidate."""
    values = [str(error) for error in errors]
    lowered = [value.casefold() for value in values]
    citation_valid = not any(
        "evidence_ids" in value
        or "unknown evidence id" in value
        or "references section" in value
        or "citation coverage" in value
        or "no core findings" in value
        for value in lowered
    )
    support_valid = not any(
        "numbers or units" in value
        or "association into causation" in value
        or "preclinical evidence" in value
        or "non-significant result" in value
        or "speculative source" in value
        for value in lowered
    )
    safety_valid = not any(
        "personalized diagnosis" in value
        or "treatment or medication instruction" in value
        or "personalized medication guidance" in value
        or "server-controlled templates" in value
        for value in lowered
    )
    questions_valid = not any(
        "duplicates another question" in value
        or "is not a question" in value
        or "question_suggestions[" in value
        for value in lowered
    )
    report_valid = not any(
        "provider output" in value
        or "schema_version" in value
        or "report must" in value
        for value in lowered
    )
    return {
        "pipeline_status": "rejected",
        "report_valid": report_valid,
        "citation_valid": citation_valid,
        "support_valid": support_valid,
        "safety_valid": safety_valid,
        "questions_valid": questions_valid,
        "error_codes": _stable_error_codes(values),
        "validator_errors": list(dict.fromkeys(values)),
        "provider_call_count": provider_call_count,
    }


def evaluate_literature_matching(case: EvaluationCase, dataset_root: Path) -> dict[str, Any]:
    """Run the deterministic matcher over a frozen local article fixture."""
    finding = MatchableFinding.model_validate(case.input.get("finding", {}))
    articles = _load_articles(case, dataset_root)
    config = case.input.get("matcher", {})
    config = config if isinstance(config, dict) else {}
    result = match_articles(
        [finding],
        articles,
        min_score=int(config.get("min_score", 40)),
        min_condition_score=int(config.get("min_condition_score", 15)),
        max_articles=int(config.get("max_articles", 50)),
        max_per_finding=int(config.get("max_per_finding", 5)),
    )
    finding_result = result.findings[0] if result.findings else None
    cards = finding_result.candidates if finding_result else []
    return {
        "match_status": finding_result.match_status if finding_result else "no_candidates",
        "candidate_ids": [card.article_id for card in cards],
        "candidate_scores": [card.relevance_score for card in cards],
        "study_categories": [card.study_category for card in cards],
        "development_phases": [card.development_phase for card in cards],
        "reason_features": [
            [feature.feature for feature in card.match_features]
            for card in cards
        ],
        "reason_complete": (
            all(bool(card.match_reasons) for card in cards)
            if cards
            else None
        ),
        "abstained": not bool(cards),
        "excluded_articles": dict(sorted(result.excluded_articles.items())),
        "article_count": result.article_count,
    }


def evaluate_clinician_questions(case: EvaluationCase, _dataset_root: Path) -> dict[str, Any]:
    """Normalize server-owned question templates and validate their bindings."""
    context = _build_context(case.input)
    try:
        report = MedicalInsightReport.model_validate(case.input.get("report", {}))
    except ValidationError as exc:
        return {
            "report_valid": False,
            "normalization_valid": False,
            "all_bound": False,
            "question_count": 0,
            "normalized_topics": [],
            "errors": ["report_schema_invalid", *[str(item["type"]) for item in exc.errors()]],
        }

    try:
        normalized = normalize_question_suggestions(
            report.question_suggestions,
            report.language,
            report=report,
            context=context,
        )
    except QuestionTemplateError as exc:
        return {
            "report_valid": True,
            "normalization_valid": False,
            "all_bound": False,
            "question_count": 0,
            "normalized_topics": [],
            "errors": list(exc.errors),
        }

    normalized_report = report.model_copy(update={"question_suggestions": normalized})
    questions = validate_questions(normalized_report, context)
    citations = validate_citations(normalized_report, context)
    safety = validate_safety(normalized_report)
    support = validate_support(normalized_report, context)
    evidence_ids = context.evidence_by_id
    all_bound = bool(normalized) and all(
        item.source_kind
        and item.source_id
        and item.evidence_ids
        and all(value in evidence_ids for value in item.evidence_ids)
        for item in normalized
    )
    return {
        "report_valid": True,
        "normalization_valid": True,
        "all_bound": all_bound,
        "question_count": len(normalized),
        "normalized_topics": [item.topic for item in normalized],
        "source_ids": [item.source_id for item in normalized],
        "evidence_ids": [list(item.evidence_ids) for item in normalized],
        "questions_valid": questions.valid,
        "citation_valid": citations.valid,
        "support_valid": support.valid,
        "safety_valid": safety.valid,
        "errors": list(dict.fromkeys([
            *questions.errors,
            *citations.errors,
            *support.errors,
            *safety.errors,
        ])),
    }


def evaluate_visit_preparation(case: EvaluationCase, _dataset_root: Path) -> dict[str, Any]:
    """Exercise the offline, server-owned visit-preparation state machine.

    The repository/API integration tests cover SQL transactions and HTTP
    permissions. These cases keep the evaluation suite filesystem-only while
    replaying the same invariants: a report suggestion is normalized on the
    server, source versions must be current, user state survives a refresh,
    and a brief stores a separate evidence snapshot.
    """
    payload = case.input
    try:
        report = MedicalInsightReport.model_validate(payload.get("report", {}))
        context = _build_context(payload)
    except (ValidationError, EvaluationAdapterError) as exc:
        return {
            "report_valid": False,
            "normalization_valid": False,
            "save_status": "rejected",
            "question_count": 0,
            "brief_status": "not_created",
            "error_code": "visit_preparation_input_invalid",
            "errors": [str(exc)],
        }

    try:
        normalized = normalize_question_suggestions(
            report.question_suggestions,
            report.language,
            report=report,
            context=context,
        )
    except QuestionTemplateError as exc:
        return {
            "report_valid": True,
            "normalization_valid": False,
            "save_status": "rejected",
            "question_count": 0,
            "brief_status": "not_created",
            "error_code": "visit_preparation_source_invalid",
            "errors": list(exc.errors),
        }

    document = payload.get("document", {})
    if not isinstance(document, dict):
        raise EvaluationAdapterError("visit preparation document must be an object")
    document_hash = str(document.get("parsed_source_hash") or "")
    analysis_hash = str(document.get("analysis_parsed_source_hash") or document_hash)
    analysis_validated = document.get("validation_status") == "validated"
    analysis_current = bool(document.get("is_current", True))
    rows: dict[str, dict[str, Any]] = {}
    normalized_by_id = {item.id: item for item in normalized}
    topic_keys: dict[tuple[str, str], str] = {}
    positions = 0
    last_save_status = "not_attempted"
    last_error = ""
    client_payload_ignored = False
    snapshots: list[dict[str, Any]] = []

    seed_questions = payload.get("seed_questions", [])
    if not isinstance(seed_questions, list):
        raise EvaluationAdapterError("visit preparation seed_questions must be a list")
    for seed in seed_questions:
        if not isinstance(seed, dict) or not seed.get("id"):
            raise EvaluationAdapterError("visit preparation seed question is invalid")
        row = {
            "id": str(seed["id"]),
            "status": str(seed.get("status") or "saved"),
            "priority": int(seed.get("priority") or 2),
            "position": positions,
            "user_note": str(seed.get("user_note") or ""),
            "version": 1,
            "question": str(seed.get("question") or ""),
            "rationale": str(seed.get("rationale") or ""),
            "category": str(seed.get("category") or "seed"),
            "topic": str(seed.get("topic") or seed["id"]),
            "source_kind": str(seed.get("source_kind") or "seed"),
            "source_id": str(seed.get("source_id") or seed["id"]),
            "evidence_ids": [str(value) for value in seed.get("evidence_ids", [])],
            "parsed_source_hash": str(seed.get("parsed_source_hash") or analysis_hash),
        }
        rows[row["id"]] = row
        positions += 1

    operations = payload.get("operations", [])
    if not isinstance(operations, list):
        raise EvaluationAdapterError("visit preparation operations must be a list")

    for operation in operations:
        if not isinstance(operation, dict):
            raise EvaluationAdapterError("visit preparation operation must be an object")
        action = str(operation.get("action") or "")
        if action == "save":
            suggestion_id = str(operation.get("suggestion_id") or "")
            suggestion = normalized_by_id.get(suggestion_id)
            if suggestion is None:
                last_save_status = "rejected"
                last_error = "clinician_question_not_found"
                continue
            client_payload = operation.get("client_payload")
            if isinstance(client_payload, dict) and any(
                key in client_payload
                for key in ("question", "rationale", "evidence_ids", "source_id")
            ):
                client_payload_ignored = True
            if not analysis_validated:
                last_save_status = "rejected"
                last_error = "clinician_question_analysis_unavailable"
                continue
            if not analysis_current or analysis_hash != document_hash:
                last_save_status = "rejected"
                last_error = "clinician_question_source_outdated"
                continue

            topic_key = (suggestion.category, suggestion.topic or "")
            existing_id = topic_keys.get(topic_key)
            if existing_id:
                row = rows[existing_id]
                row.update(_visit_question_source(suggestion, analysis_hash))
                last_save_status = "refreshed"
            else:
                row = {
                    "id": suggestion.id,
                    "status": "saved",
                    "priority": 2,
                    "position": positions,
                    "user_note": "",
                    "version": 1,
                    **_visit_question_source(suggestion, analysis_hash),
                }
                positions += 1
                rows[row["id"]] = row
                topic_keys[topic_key] = row["id"]
                last_save_status = "created"
            continue

        if action == "update":
            question_id = str(operation.get("question_id") or "")
            row = rows.get(question_id)
            if row is None:
                last_error = "clinician_question_not_found"
                continue
            if operation.get("status") is not None:
                row["status"] = str(operation["status"])
            if operation.get("priority") is not None:
                row["priority"] = int(operation["priority"])
            if operation.get("user_note") is not None:
                row["user_note"] = str(operation["user_note"])
            row["version"] += 1
            continue

        if action == "reparse":
            document_hash = str(operation.get("parsed_source_hash") or "")
            analysis_current = False
            continue

        if action == "create_brief":
            question_ids = operation.get("question_ids", [])
            if not isinstance(question_ids, list):
                raise EvaluationAdapterError("visit brief question_ids must be a list")
            if not 1 <= len(question_ids) <= 10 or len(set(question_ids)) != len(question_ids):
                last_error = "visit_brief_invalid_selection"
                continue
            selected = [rows.get(str(question_id)) for question_id in question_ids]
            if any(row is None for row in selected):
                last_error = "visit_brief_question_not_found"
                continue
            if any(row["status"] == "dismissed" for row in selected if row):
                last_error = "visit_brief_question_dismissed"
                continue
            if any(
                _visit_source_status(row, document_hash, analysis_validated, analysis_current)
                != "current"
                for row in selected
                if row
            ):
                last_error = "visit_brief_source_outdated"
                continue
            include_notes = bool(operation.get("include_user_notes", False))
            snapshots = [
                {
                    "question_id": row["id"],
                    "question": row["question"],
                    "user_note": row["user_note"] if include_notes else "",
                    "evidence_ids": list(row["evidence_ids"]),
                }
                for row in selected
                if row
            ]
            last_error = ""
            continue

        raise EvaluationAdapterError(f"unknown visit preparation action {action!r}")

    current_notes = [rows[item["question_id"]]["user_note"] for item in snapshots]
    return {
        "report_valid": True,
        "normalization_valid": True,
        "save_status": last_save_status,
        "question_count": len(rows),
        "question_statuses": [row["status"] for row in sorted(rows.values(), key=lambda item: item["position"])],
        "question_priorities": [row["priority"] for row in sorted(rows.values(), key=lambda item: item["position"])],
        "question_notes": [row["user_note"] for row in sorted(rows.values(), key=lambda item: item["position"])],
        "source_statuses": [
            _visit_source_status(row, document_hash, analysis_validated, analysis_current)
            for row in sorted(rows.values(), key=lambda item: item["position"])
        ],
        "safe_questions": [row["question"] for row in sorted(rows.values(), key=lambda item: item["position"])],
        "client_payload_ignored": client_payload_ignored,
        "brief_status": "created" if snapshots else ("rejected" if last_error.startswith("visit_brief_") else "not_created"),
        "brief_item_count": len(snapshots),
        "brief_question_ids": [item["question_id"] for item in snapshots],
        "brief_evidence_ids": [item["evidence_ids"] for item in snapshots],
        "brief_user_notes": [item["user_note"] for item in snapshots],
        "snapshot_immutable": bool(snapshots) and snapshots[0]["user_note"] != (current_notes[0] if current_notes else ""),
        "error_code": last_error,
        "errors": [last_error] if last_error else [],
    }


def _visit_question_source(item: Any, parsed_source_hash: str) -> dict[str, Any]:
    """Copy only normalized server-owned question data into the replay state."""
    return {
        "question": item.question,
        "rationale": item.rationale,
        "category": item.category,
        "topic": item.topic,
        "source_kind": item.source_kind,
        "source_id": item.source_id,
        "evidence_ids": list(item.evidence_ids),
        "parsed_source_hash": parsed_source_hash,
    }


def _visit_source_status(
    row: dict[str, Any],
    document_hash: str,
    analysis_validated: bool,
    analysis_current: bool,
) -> str:
    if not analysis_validated:
        return "unavailable"
    if not analysis_current or row.get("parsed_source_hash") != document_hash:
        return "outdated"
    return "current"


def _build_context(payload: Mapping[str, Any]) -> Any:
    chunks = payload.get("chunks", [])
    if not isinstance(chunks, list):
        raise EvaluationAdapterError("evaluation chunks must be a list")
    return ContextBuilder().build(
        chunks,
        sections=payload.get("sections") if isinstance(payload.get("sections"), list) else None,
        title=str(payload.get("title") or "Evaluation document"),
        document_kind=str(payload.get("document_kind") or "research_paper"),
        language=str(payload.get("language") or "en"),
        max_input_tokens=int(payload.get("max_input_tokens", 12000)),
        redact_pii=True,
    )


def _load_articles(case: EvaluationCase, dataset_root: Path) -> list[dict[str, Any]]:
    inline = case.input.get("articles")
    if inline is not None:
        if not isinstance(inline, list):
            raise EvaluationAdapterError("inline article fixture must be a list")
        return [dict(item) for item in inline if isinstance(item, dict)]
    if len(case.fixtures) != 1:
        raise EvaluationAdapterError("literature cases require exactly one article fixture")
    path = (dataset_root / case.fixtures[0]).resolve()
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EvaluationAdapterError("literature article fixture is invalid") from exc
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise EvaluationAdapterError("literature article fixture must contain objects")
    return [dict(item) for item in value]


def _stable_error_codes(errors: list[str]) -> list[str]:
    """Reduce validator prose to stable categories for evaluation output."""
    codes: list[str] = []
    for error in errors:
        value = str(error).casefold()
        if "causation" in value:
            code = "association_as_causation"
        elif "preclinical" in value or "human efficacy" in value:
            code = "preclinical_as_human"
        elif "non-significant" in value or "no effect" in value:
            code = "nonsignificant_as_no_effect"
        elif "speculative" in value:
            code = "speculation_as_fact"
        elif "number" in value or "unit" in value:
            code = "unsupported_number"
        elif "references" in value:
            code = "references_as_evidence"
        elif "treatment" in value or "diagnosis" in value or "medication" in value:
            code = "personalized_medical_advice"
        elif "evidence" in value:
            code = "evidence_validation"
        else:
            code = "validation_error"
        if code not in codes:
            codes.append(code)
    return codes
