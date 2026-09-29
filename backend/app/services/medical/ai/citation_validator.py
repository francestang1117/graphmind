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
_NON_MEDICAL_SECTION_TYPES = _REFERENCE_SECTION_TYPES | {
    "supplementary",
    "acknowledgements",
    "acknowledgments",
    "funding",
    "author_contributions",
    "conflicts_of_interest",
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
            source_section = _section_key(source.section_type)
            if source_section in _NON_MEDICAL_SECTION_TYPES:
                errors.append(
                    f"{label} cites a references section"
                    if source_section in _REFERENCE_SECTION_TYPES
                    else f"{label} cites a non-medical section"
                )
                item_valid = False
                continue
            if (
                getattr(item, "id", None) in _author_conclusion_ids(report)
                and _citation_span(report, item.id, source) is None
            ):
                errors.append(
                    f"{label} could not be matched to a precise source range"
                )
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
            if not item or _section_key(item.section_type) in _NON_MEDICAL_SECTION_TYPES:
                continue
            key = (finding_id, evidence_id)
            if key in seen:
                continue
            seen.add(key)
            span = _citation_span(
                report,
                finding_id,
                item,
            )
            if span is None:
                continue
            quoted_text, character_start, character_end = span
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
                    "quoted_text": quoted_text,
                    "character_start": character_start,
                    "character_end": character_end,
                    "quality_score": item.quality_score,
                    "quality_flags": list(item.quality_flags),
                }
            )
    return rows


def _citation_span(
    report: MedicalInsightReport,
    finding_id: str,
    item: EvidenceItem,
) -> tuple[str, int | None, int | None] | None:
    """Prefer an exact claim range while preserving safe fallback behavior."""
    conclusion = next(
        (entry for entry in report.authors_conclusions if entry.id == finding_id),
        None,
    )
    statement = _claim_statement(report, finding_id)
    if not statement:
        return item.text, item.character_start, item.character_end

    source, offsets = _normalized_with_offsets(item.text)
    statement = " ".join(statement.split()).strip()
    start = source.find(statement)
    if not statement or start < 0:
        source, offsets = _normalized_with_offsets(
            item.text,
            remove_soft_hyphens=True,
        )
        statement = _normalized_for_match(
            statement,
            remove_soft_hyphens=True,
        )
        start = source.find(statement)
    if start < 0:
        source, offsets = _normalized_with_offsets(
            item.text,
            compact_hyphen_spacing=True,
        )
        statement = _normalized_for_match(
            statement,
            compact_hyphen_spacing=True,
        )
        start = source.find(statement)
    if not statement or start < 0:
        # Conclusion claims must fail closed because their chunk can contain
        # disclosures or references. Other claim types may be provider
        # summaries, so keep their existing whole-chunk fallback when an
        # exact extractive range is unavailable.
        return (
            None
            if conclusion is not None
            else (item.text, item.character_start, item.character_end)
        )

    end = start + len(statement)
    raw_start = offsets[start]
    raw_end = offsets[end - 1] + 1
    character_start = (
        item.character_start + raw_start
        if item.character_start is not None
        else None
    )
    character_end = (
        item.character_start + raw_end
        if item.character_start is not None
        else item.character_end
    )
    return item.text[raw_start:raw_end], character_start, character_end


def _claim_statement(report: MedicalInsightReport, finding_id: str) -> str:
    if finding_id == "overview":
        return report.overview.summary

    for field_name in (
        "key_findings",
        "authors_conclusions",
        "limitations",
        "what_it_means",
        "what_it_does_not_mean",
        "applicability",
        "future_research",
    ):
        for item in getattr(report, field_name):
            if item.id == finding_id:
                return item.statement

    for field_name, item in report.study_methods.model_dump().items():
        if finding_id == f"study_methods.{field_name}":
            return str(item.get("value") or "")
    return ""


def _normalized_with_offsets(
    text: str,
    *,
    remove_soft_hyphens: bool = False,
    compact_hyphen_spacing: bool = False,
) -> tuple[str, list[int]]:
    """Normalize source text while retaining offsets into the raw text."""
    characters: list[str] = []
    offsets: list[int] = []
    index = 0
    while index < len(text):
        character = text[index]
        if remove_soft_hyphens and character == "-":
            next_index = index + 1
            if next_index < len(text) and text[next_index].isspace():
                index = next_index
                while index < len(text) and text[index].isspace():
                    index += 1
                continue
        if character.isspace():
            if compact_hyphen_spacing and characters and characters[-1] == "-":
                index += 1
                continue
            if characters and characters[-1] != " ":
                characters.append(" ")
                offsets.append(index)
            index += 1
            continue
        characters.append(character)
        offsets.append(index)
        index += 1
    if characters and characters[-1] == " ":
        characters.pop()
        offsets.pop()
    return "".join(characters), offsets


def _normalized_for_match(
    text: str,
    *,
    remove_soft_hyphens: bool = False,
    compact_hyphen_spacing: bool = False,
) -> str:
    return _normalized_with_offsets(
        text,
        remove_soft_hyphens=remove_soft_hyphens,
        compact_hyphen_spacing=compact_hyphen_spacing,
    )[0]


def _author_conclusion_ids(report: MedicalInsightReport) -> set[str]:
    return {item.id for item in report.authors_conclusions}


def _core_items(
    report: MedicalInsightReport,
) -> Iterable[tuple[str, Any, list[str]]]:
    yield "overview", report.overview, report.overview.evidence_ids
    for field_name in (
        "key_findings",
        "authors_conclusions",
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
    for index, item in enumerate(report.question_suggestions, start=1):
        yield f"question_suggestions[{index}]", item, item.evidence_ids
    for field_name, item in report.study_methods.model_dump().items():
        if item["support_status"] != "not_reported":
            yield f"study_methods.{field_name}", item, item["evidence_ids"]


def _report_citations(report: MedicalInsightReport) -> Iterable[tuple[str, list[str]]]:
    yield "overview", report.overview.evidence_ids
    for field_name in (
        "key_findings",
        "authors_conclusions",
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
    for item in report.question_suggestions:
        yield f"question:{item.id}", item.evidence_ids
    for field_name, item in report.study_methods.model_dump().items():
        if item["support_status"] != "not_reported":
            yield f"study_methods.{field_name}", item["evidence_ids"]


def _section_key(value: str) -> str:
    """Keep section checks stable across parser casing and separators."""
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
