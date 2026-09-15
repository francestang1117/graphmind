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

    def release_confirmed(self, query: LiteratureQuery) -> None:
        if query.resolution_status != "ready" or not query.normalized_query:
            return
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

    if query.resolution_status == "ready":
        try:
            # Reuse the production confirmation contract before entering the
            # recording repository/queue/provider boundary.
            confirm_literature_query(
                query,
                external_search_confirmed=True,
                query_fingerprint=query.query_hash,
            )
        except LiteratureQueryError as exc:
            raise EvaluationAdapterError("safe literature confirmation failed") from exc
    boundary.release_confirmed(query)
    normalized_query = query.normalized_query
    fragments = [str(value) for value in case.input.get("leak_checks", [])]
    released_query = "\n".join(boundary.released_queries)
    return {
        "resolution_status": query.resolution_status,
        "external_query_allowed": query.resolution_status == "ready" and bool(normalized_query),
        "external_query_count": len(boundary.provider.calls),
        "repository_create_count": boundary.repository_create_count,
        "queue_count": boundary.queue_count,
        "provider_search_count": len(boundary.provider.calls),
        "released_queries": list(boundary.released_queries),
        "normalized_terms": [item.normalized for item in query.detected_concepts],
        "concept_ids": [item.concept_id for item in query.detected_concepts if item.concept_id],
        "normalized_query": normalized_query,
        "error_code": None,
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
