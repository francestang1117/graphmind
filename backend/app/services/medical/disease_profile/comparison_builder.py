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
_NOT_REPORTED = {
    "en": "The selected analysis evidence did not report this field.",
    "zh": "所选分析证据未报告此字段。",
    "ja": "選択した分析証拠ではこの項目は報告されていません。",
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
                    "question": question,
                    "rationale": rationale,
                    "document_id": document_id,
                    "evidence": limitations[0].evidence,
                }
            )

    preview = ComparisonPreview(
        concept_id=concept_id,
        documents=documents,
        discussion_questions=questions[:_MAX_QUESTIONS],
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
            methods[field] = ComparisonMethod(
                value=_NOT_REPORTED[language],
                support_status="not_reported",
            )
            continue
        value = str(raw_value.get("value") or "").strip()
        sources = _sources_for_ids(
            raw_value.get("evidence_ids"),
            evidence,
            document_id=document_id,
            run_id=run_id,
        )
        if not value or not sources:
            methods[field] = ComparisonMethod(
                value="",
                support_status="source_unavailable",
                warnings=["source_unavailable"],
            )
            continue
        if status not in {"supported", "partially_supported", "uncertain"}:
            status = "uncertain"
        methods[field] = ComparisonMethod(
            value=value,
            support_status=status,
            evidence=sources,
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
                "question": question,
                "rationale": rationale,
                "document_id": document_id,
                "evidence": method.evidence,
            }
            break
    return methods, method_question


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
        sources = _sources_for_ids(
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
) -> list[ComparisonEvidence]:
    result: list[ComparisonEvidence] = []
    seen: set[str] = set()
    for evidence_id in _string_list(evidence_ids):
        if evidence_id in seen:
            continue
        seen.add(evidence_id)
        item = evidence.get(evidence_id)
        if not item:
            continue
        section_type = str(item.get("section_type") or "unknown").strip().lower()
        if section_type in _REFERENCE_SECTIONS:
            continue
        quote = str(item.get("quote") or item.get("quoted_text") or "").strip()
        if not quote:
            continue
        result.append(
            ComparisonEvidence(
                document_id=document_id,
                analysis_run_id=run_id,
                evidence_id=evidence_id,
                quote=quote,
                section_type=str(item.get("section_type") or "unknown"),
                section_title=str(item.get("section_title") or ""),
                page_start=_page_number(item.get("page_start")),
                page_end=_page_number(item.get("page_end")),
            )
        )
        if len(result) >= 5:
            break
    return result


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
