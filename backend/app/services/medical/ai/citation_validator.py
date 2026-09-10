"""Check that report claims point to the evidence sent to the provider."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from app.services.medical.ai.context_builder import AnalysisContext, EvidenceItem
from app.services.medical.ai.models import MedicalInsightReport


_REFERENCE_SECTION_TYPES = {
    "references",
    "reference",
    "bibliography",
    "works_cited",
    "reference_list",
    "references_and_bibliography",
}


@dataclass
class CitationValidation:
    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    coverage: float = 0.0
    cited_evidence_ids: set[str] = field(default_factory=set)


def validate_citations(
    report: MedicalInsightReport,
    context: AnalysisContext,
) -> CitationValidation:
    """Require citations for every factual field that will be shown as a claim."""
    evidence = context.evidence_by_id
    errors: list[str] = []
    cited: set[str] = set()
    core_items = list(_core_items(report))
    supported_items = 0

    for label, item, evidence_ids in core_items:
        ids = [str(value) for value in evidence_ids]
        if not ids:
            errors.append(f"{label} has no evidence_ids")
            continue

        item_valid = True
        for evidence_id in ids:
            source = evidence.get(evidence_id)
            if source is None:
                errors.append(f"{label} cites unknown evidence id {evidence_id}")
                item_valid = False
                continue
            cited.add(evidence_id)
            if _section_key(source.section_type) in _REFERENCE_SECTION_TYPES:
                errors.append(f"{label} cites a references section")
                item_valid = False
        if item_valid:
            supported_items += 1

    coverage = supported_items / len(core_items) if core_items else 0.0
    if not core_items:
        errors.append("report has no core findings")
    if coverage < 1.0:
        errors.append("citation coverage is incomplete")

    return CitationValidation(
        valid=not errors,
        errors=errors,
        warnings=[],
        coverage=round(coverage, 4),
        cited_evidence_ids=cited,
    )


def evidence_rows(
    report: MedicalInsightReport,
    context: AnalysisContext,
) -> list[dict[str, Any]]:
    """Flatten report citations into rows ready for a database transaction."""
    by_id = context.evidence_by_id
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    for finding_id, evidence_ids in _report_citations(report):
        for evidence_id in evidence_ids:
            item = by_id.get(evidence_id)
            if not item or _section_key(item.section_type) in _REFERENCE_SECTION_TYPES:
                continue
            key = (finding_id, evidence_id)
            if key in seen:
                continue
            seen.add(key)
            rows.append(
                {
                    "finding_id": finding_id,
                    "evidence_id": evidence_id,
                    "chunk_id": item.chunk_id,
                    "section_id": item.section_id,
                    "section_type": item.section_type,
                    "section_title": item.section_title,
                    "page_start": item.page_start,
                    "page_end": item.page_end,
                    "quoted_text": item.text,
                    "character_start": item.character_start,
                    "character_end": item.character_end,
                }
            )
    return rows


def _core_items(
    report: MedicalInsightReport,
) -> Iterable[tuple[str, Any, list[str]]]:
    yield "overview", report.overview, report.overview.evidence_ids
    for field_name in (
        "key_findings",
        "limitations",
        "what_it_means",
        "what_it_does_not_mean",
        "applicability",
        "future_research",
    ):
        for index, item in enumerate(getattr(report, field_name), start=1):
            yield f"{field_name}[{index}]", item, item.evidence_ids
    for index, item in enumerate(report.medical_terms, start=1):
        yield f"medical_terms[{index}]", item, item.evidence_ids
    for field_name, item in report.study_methods.model_dump().items():
        if item["support_status"] != "not_reported":
            yield f"study_methods.{field_name}", item, item["evidence_ids"]


def _report_citations(report: MedicalInsightReport) -> Iterable[tuple[str, list[str]]]:
    yield "overview", report.overview.evidence_ids
    for field_name in (
        "key_findings",
        "limitations",
        "what_it_means",
        "what_it_does_not_mean",
        "applicability",
        "future_research",
    ):
        for item in getattr(report, field_name):
            yield item.id, item.evidence_ids
    for item in report.medical_terms:
        yield item.term, item.evidence_ids
    for field_name, item in report.study_methods.model_dump().items():
        if item["support_status"] != "not_reported":
            yield f"study_methods.{field_name}", item["evidence_ids"]


def _section_key(value: str) -> str:
    """Keep section checks stable across parser casing and separators."""
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
