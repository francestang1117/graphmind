"""Build an evidence-bound, non-interpretive disease comparison preview."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from app.services.medical.disease_profile.models import (
    ComparisonDocument,
    ComparisonEvidence,
    ComparisonMethod,
    ComparisonPreview,
)


_METHOD_FIELDS = (
    "design",
    "population",
    "human_animal_in_vitro",
    "sample_size",
    "comparator",
)
_FINDING_SECTIONS = ("key_findings", "limitations")
_REFERENCE_SECTIONS = {"references", "bibliography"}
_MAX_FINDINGS = 10
_MAX_QUESTIONS = 3
_MAX_QUOTE_CHARS = 5000
_NOT_REPORTED = {
    "en": {
        "not_reported_in_source": "The source evidence states that this field was not reported.",
        "not_extracted_from_analyzed_text": "This field was not confirmed in the analyzed text.",
        "source_unreadable": "This field could not be checked because the source text was not readable.",
    },
    "zh": {
        "not_reported_in_source": "原文证据说明该字段未报告。",
        "not_extracted_from_analyzed_text": "在已分析文本中未能确认该字段。",
        "source_unreadable": "由于原文无法可靠读取，无法检查该字段。",
    },
    "ja": {
        "not_reported_in_source": "出典の証拠では、この項目は報告されていません。",
        "not_extracted_from_analyzed_text": "分析した本文では、この項目を確認できませんでした。",
        "source_unreadable": "本文を信頼して読み取れないため、この項目を確認できません。",
    },
}
_QUESTION_TEMPLATES = {
    "en": {
        "population": (
            "What should we clarify about the study population before applying these findings?",
            "The study population determines who the reported findings describe.",
        ),
        "design": (
            "What should we clarify about the study design and comparison group?",
            "The study design and comparison group affect how the reported findings should be read.",
        ),
        "limitations": (
            "Which limitations should we discuss with a healthcare professional?",
            "The selected source reports limitations that may affect interpretation.",
        ),
    },
    "zh": {
        "population": (
            "在理解这些结果的适用范围前，还需要向医生确认研究人群的哪些信息？",
            "研究人群决定了这些结果实际描述的是哪些人。",
        ),
        "design": (
            "关于研究设计和对照组，还需要向医生确认哪些信息？",
            "研究设计和对照组会影响这些结果应如何理解。",
        ),
        "limitations": (
            "这些研究局限中，哪些值得带去和医生进一步讨论？",
            "所选资料报告了可能影响结果解读的研究局限。",
        ),
    },
    "ja": {
        "population": (
            "この結果をどの範囲に当てはめられるか、研究対象について医療者に何を確認すべきですか？",
            "研究対象は、報告された結果がどの人々について述べているかを示します。",
        ),
        "design": (
            "研究デザインと比較群について、医療者に何を確認すべきですか？",
            "研究デザインと比較群は、報告された結果の読み方に関係します。",
        ),
        "limitations": (
            "この研究の限界のうち、医療者とさらに話し合うべき点はどれですか？",
            "選択した資料には、結果の解釈に影響し得る限界が報告されています。",
        ),
    },
}


def build_comparison_preview(
    *,
    concept_id: str,
    inputs: Sequence[Mapping[str, Any]],
    language: str = "en",
) -> ComparisonPreview:
    """Build a deterministic comparison without comparing study conclusions.

    ``inputs`` must already be scoped and current-validated by the repository
    and service. The builder still checks its local evidence bindings so a
    malformed snapshot cannot turn an unsupported value into a cited one.
    """
    locale = language if language in _QUESTION_TEMPLATES else "en"
    documents: list[ComparisonDocument] = []
    questions: list[dict[str, Any]] = []
    warnings: list[str] = []

    for record in inputs:
        document = record.get("document") or {}
        analysis = _current_analysis(record)
        if not analysis:
            continue
        run = analysis.get("run") or {}
        report = analysis.get("report")
        if not isinstance(report, Mapping):
            continue
        document_id = str(document.get("document_id") or "")
        run_id = str(run.get("run_id") or "")
        evidence = _evidence_index(analysis.get("evidence"))
        methods, method_question = _build_methods(
            report,
            evidence,
            document_id=document_id,
            run_id=run_id,
            language=locale,
        )
        findings, findings_total, findings_truncated = _build_findings(
            report.get("key_findings"),
            evidence,
            document_id=document_id,
            run_id=run_id,
        )
        limitations, limitations_total, limitations_truncated = _build_findings(
            report.get("limitations"),
            evidence,
            document_id=document_id,
            run_id=run_id,
        )
        coverage, coverage_warning = _build_coverage(report)
        if coverage_warning:
            warnings.append(coverage_warning)

        comparison_document = ComparisonDocument(
            document_id=document_id,
            title=str(document.get("title") or "Untitled document"),
            document_kind=str(document.get("document_kind") or "unknown"),
            document_date=str(document.get("document_date") or ""),
            open_filename=str(
                document.get("open_filename") or document.get("filename") or ""
            ),
            analysis_run_id=run_id,
            parsed_source_hash=str(run.get("parsed_source_hash") or ""),
            coverage_status=coverage["status"],
            coverage=coverage,
            methods=methods,
            findings=findings,
            findings_total=findings_total,
            findings_truncated=findings_truncated,
            limitations=limitations,
            limitations_total=limitations_total,
            limitations_truncated=limitations_truncated,
        )
        documents.append(comparison_document)

        if method_question:
            questions.append(method_question)
        if limitations:
            question, rationale = _QUESTION_TEMPLATES[locale]["limitations"]
            questions.append(
                {
                    "id": f"comparison:{document_id}:limitations",
                    "topic": "study_limitation",
                    "question": question,
                    "rationale": rationale,
                    "document_id": document_id,
                    "document_ids": [document_id],
                    "analysis_run_ids": [str(run.get("run_id") or "")],
                    "evidence": limitations[0]["evidence"],
                    "evidence_total": limitations[0]["evidence_total"],
                    "evidence_truncated": limitations[0]["evidence_truncated"],
                }
            )

    preview = ComparisonPreview(
        concept_id=concept_id,
        documents=documents,
        discussion_questions=_merge_questions(questions)[:_MAX_QUESTIONS],
        warnings=_unique_strings(warnings)[:20],
    )
    return preview


def _current_analysis(record: Mapping[str, Any]) -> Mapping[str, Any] | None:
    analyses = record.get("analyses") or []
    for analysis in analyses:
        if not isinstance(analysis, Mapping):
            continue
        if analysis.get("valid") and isinstance(analysis.get("report"), Mapping):
            return analysis
    return None


def _build_methods(
    report: Mapping[str, Any],
    evidence: Mapping[str, Mapping[str, Any]],
    *,
    document_id: str,
    run_id: str,
    language: str,
) -> tuple[dict[str, ComparisonMethod], dict[str, Any] | None]:
    raw_methods = report.get("study_methods")
    raw_methods = raw_methods if isinstance(raw_methods, Mapping) else {}
    methods: dict[str, ComparisonMethod] = {}
    for field in _METHOD_FIELDS:
        raw_value = raw_methods.get(field)
        raw_value = raw_value if isinstance(raw_value, Mapping) else {}
        status = str(raw_value.get("support_status") or "uncertain")
        if status == "not_reported":
            missing_reason = str(
                raw_value.get("missing_reason") or "not_reported_in_source"
            )
            if missing_reason not in _NOT_REPORTED[language]:
                missing_reason = "not_extracted_from_analyzed_text"
            methods[field] = ComparisonMethod(
                value=_NOT_REPORTED[language][missing_reason],
                support_status="not_reported",
                missing_reason=missing_reason,
            )
            continue
        value = str(raw_value.get("value") or "").strip()
        sources, evidence_total, evidence_truncated = _sources_for_ids(
            raw_value.get("evidence_ids"),
            evidence,
            document_id=document_id,
            run_id=run_id,
        )
        if not value or not sources:
            methods[field] = ComparisonMethod(
                value="",
                support_status="source_unavailable",
                evidence_total=evidence_total,
                evidence_truncated=evidence_truncated,
                warnings=["source_unavailable"],
                missing_reason="source_unreadable",
            )
            continue
        if status not in {"supported", "partially_supported", "uncertain"}:
            status = "uncertain"
        methods[field] = ComparisonMethod(
            value=value,
            support_status=status,
            evidence=sources,
            evidence_total=evidence_total,
            evidence_truncated=evidence_truncated,
        )

    method_question = None
    for topic, method in (
        ("population", methods["population"]),
        ("design", methods["design"]),
    ):
        if method.evidence:
            question, rationale = _QUESTION_TEMPLATES[language][topic]
            method_question = {
                "id": f"comparison:{document_id}:{topic}",
                "topic": topic,
                "question": question,
                "rationale": rationale,
                "document_id": document_id,
                "document_ids": [document_id],
                "analysis_run_ids": [run_id],
                "evidence": method.evidence,
                "evidence_total": method.evidence_total,
                "evidence_truncated": method.evidence_truncated,
            }
            break
    return methods, method_question


def _merge_questions(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge repeated template questions while keeping every valid source."""

    def evidence_value(item: Any, key: str) -> Any:
        if isinstance(item, Mapping):
            return item.get(key)
        return getattr(item, key, None)

    merged: dict[tuple[str, str], dict[str, Any]] = {}
    order: list[tuple[str, str]] = []
    for value in values:
        topic = str(value.get("topic") or "")
        question = " ".join(str(value.get("question") or "").split()).casefold()
        key = (topic, question)
        current = merged.get(key)
        if current is None:
            current = dict(value)
            current["id"] = f"comparison:{topic}"
            current["document_ids"] = list(dict.fromkeys(
                _string_list(value.get("document_ids"))
                or [str(value.get("document_id") or "")]
            ))
            current["analysis_run_ids"] = list(dict.fromkeys(
                _string_list(value.get("analysis_run_ids"))
            ))
            current["evidence"] = list(value.get("evidence") or [])[:5]
            merged[key] = current
            order.append(key)
            continue

        current["document_ids"] = list(dict.fromkeys(
            [*current.get("document_ids", []), *value.get("document_ids", [])]
        ))[:5]
        current["analysis_run_ids"] = list(dict.fromkeys(
            [*current.get("analysis_run_ids", []), *value.get("analysis_run_ids", [])]
        ))[:5]
        evidence = [*current.get("evidence", []), *value.get("evidence", [])]
        unique_evidence: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str]] = set()
        for item in evidence:
            identity = (
                str(evidence_value(item, "document_id") or ""),
                str(evidence_value(item, "analysis_run_id") or ""),
                str(evidence_value(item, "evidence_id") or ""),
            )
            if identity in seen:
                continue
            seen.add(identity)
            unique_evidence.append(item)
        current_total = int(current.get("evidence_total") or 0)
        value_total = int(value.get("evidence_total") or len(value.get("evidence") or []))
        current["evidence_total"] = max(
            len(unique_evidence),
            current_total + value_total,
        )
        current["evidence"] = unique_evidence[:5]
        current["evidence_truncated"] = (
            current["evidence_total"] > 5
            or bool(current.get("evidence_truncated"))
            or bool(value.get("evidence_truncated"))
        )
    return [merged[key] for key in order]


def _build_findings(
    values: Any,
    evidence: Mapping[str, Mapping[str, Any]],
    *,
    document_id: str,
    run_id: str,
) -> tuple[list[dict[str, Any]], int, bool]:
    if not isinstance(values, list):
        return [], 0, False
    collected: list[dict[str, Any]] = []
    for index, value in enumerate(values):
        if not isinstance(value, Mapping):
            continue
        statement = str(value.get("statement") or "").strip()
        if not statement:
            continue
        sources, evidence_total, evidence_truncated = _sources_for_ids(
            value.get("evidence_ids"),
            evidence,
            document_id=document_id,
            run_id=run_id,
        )
        if not sources:
            continue
        collected.append(
            {
                "id": f"{document_id}:{run_id}:{value.get('id') or index}",
                "statement": statement,
                "explanation": str(value.get("plain_explanation") or ""),
                "evidence": sources,
                "evidence_total": evidence_total,
                "evidence_truncated": evidence_truncated,
                "warnings": [],
            }
        )
    return collected[:_MAX_FINDINGS], len(collected), len(collected) > _MAX_FINDINGS


def _build_coverage(report: Mapping[str, Any]) -> tuple[dict[str, Any], str | None]:
    raw = report.get("coverage")
    if not isinstance(raw, Mapping):
        return (
            {
                "status": "unknown",
                "selected_chunks": 0,
                "total_chunks": 0,
                "included_sections": [],
                "omitted_sections": [],
            },
            "comparison_coverage_unknown",
        )
    complete = raw.get("complete")
    status = "complete" if complete is True else "partial"
    coverage = {
        "status": status,
        "selected_chunks": _nonnegative_int(raw.get("selected_chunks")),
        "total_chunks": _nonnegative_int(raw.get("total_chunks")),
        "included_sections": _string_list(raw.get("included_sections")),
        "omitted_sections": _string_list(raw.get("omitted_sections")),
    }
    return coverage, "comparison_coverage_partial" if status == "partial" else None


def _sources_for_ids(
    evidence_ids: Any,
    evidence: Mapping[str, Mapping[str, Any]],
    *,
    document_id: str,
    run_id: str,
) -> tuple[list[ComparisonEvidence], int, bool]:
    result: list[ComparisonEvidence] = []
    seen: set[str] = set()
    for evidence_id in _string_list(evidence_ids):
        if evidence_id in seen:
            continue
        seen.add(evidence_id)
        item = evidence.get(evidence_id)
        if not item:
            continue
        source_document_id = item.get("document_id")
        source_run_id = item.get("analysis_run_id") or item.get("run_id")
        if source_document_id and str(source_document_id) != document_id:
            continue
        if source_run_id and str(source_run_id) != run_id:
            continue
        section_type = str(item.get("section_type") or "unknown").strip().lower()
        if section_type in _REFERENCE_SECTIONS:
            continue
        raw_quote = str(item.get("quote") or item.get("quoted_text") or "").strip()
        if not raw_quote:
            continue
        quote_truncated = len(raw_quote) > _MAX_QUOTE_CHARS
        result.append(
            ComparisonEvidence(
                document_id=document_id,
                analysis_run_id=run_id,
                evidence_id=evidence_id,
                quote=raw_quote[:_MAX_QUOTE_CHARS],
                section_type=str(item.get("section_type") or "unknown"),
                section_title=str(item.get("section_title") or ""),
                page_start=_page_number(item.get("page_start")),
                page_end=_page_number(item.get("page_end")),
                quote_truncated=quote_truncated,
            )
        )
    evidence_total = len(result)
    return result[:5], evidence_total, evidence_total > 5


def _evidence_index(items: Any) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    if not isinstance(items, list):
        return result
    for item in items:
        if not isinstance(item, Mapping):
            continue
        value = dict(item)
        for key in (value.get("id"), value.get("evidence_id")):
            if key:
                result[str(key)] = value
    return result


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [str(item).strip() for item in value if str(item or "").strip()]


def _unique_strings(value: Any) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in _string_list(value):
        if item not in seen:
            result.append(item)
            seen.add(item)
    return result


def _nonnegative_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _page_number(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 1 else None
