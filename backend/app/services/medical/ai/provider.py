"""Provider boundary for medical insight generation.

The local provider keeps development and tests deterministic. A remote model
can be added later without changing the report or citation contracts.
"""

from __future__ import annotations

import copy
import re
from typing import Any, Protocol

from app.services.medical.ai.context_builder import AnalysisContext, EvidenceItem
from app.services.medical.ai.exceptions import ProviderUnavailable


class MedicalAIProvider(Protocol):
    name: str
    model_name: str

    def generate(self, prompt: str, context: AnalysisContext) -> Any:
        """Return a JSON-compatible report candidate."""


class ExtractiveMedicalAIProvider:
    """Create a conservative local report from selected source passages."""

    name = "extractive"

    def __init__(self, model_name: str = "extractive-v1") -> None:
        self.model_name = model_name

    def generate(self, _prompt: str, context: AnalysisContext) -> dict[str, Any]:
        evidence = context.evidence
        overview_item = _first_of(
            evidence,
            "abstract",
            "results",
            "recommendations",
            "conclusion",
            "introduction",
        ) or (evidence[0] if evidence else None)
        summary = _summary(overview_item.text if overview_item else "")
        if not summary:
            summary = "The document contains no extractable passage for a summary."

        findings = []
        for item in _take_distinct(
            evidence,
            {"results", "recommendations", "conclusion", "abstract"},
            limit=3,
        ):
            statement = _summary(item.text)
            if not statement:
                continue
            findings.append(
                _finding(
                    f"finding_{len(findings) + 1:03d}",
                    statement,
                    f"This is reported in the document's {item.section_type} section.",
                    item,
                    interpretation_type="direct_statement",
                )
            )

        if not findings and overview_item:
            findings.append(
                _finding(
                    "finding_001",
                    summary,
                    "This is the clearest extractable statement in the document.",
                    overview_item,
                    interpretation_type="summary",
                )
            )

        limitations = [
            _finding(
                f"limitation_{index:03d}",
                _summary(item.text),
                "This limitation is stated in the source document.",
                item,
                interpretation_type="direct_statement",
            )
            for index, item in enumerate(
                _take_distinct(evidence, {"limitations"}, limit=2),
                start=1,
            )
            if _summary(item.text)
        ]

        meaning_item = _first_of(evidence, "results", "recommendations", "conclusion")
        meanings = []
        if meaning_item:
            meanings.append(
                _finding(
                    "meaning_001",
                    f"Within this document, the reported result is: {_summary(meaning_item.text)}",
                    "This is a plain-language restatement of the cited passage, not a personal medical recommendation.",
                    meaning_item,
                    interpretation_type="summary",
                )
            )

        does_not_mean = []
        if limitations and meaning_item:
            does_not_mean.append(
                _finding(
                    "boundary_001",
                    "The document's findings should be read within the study population, methods, and limitations described by the authors.",
                    "The source includes limitations, so the result should not be treated as proof that it applies to every patient.",
                    _item_for_finding(limitations[0], evidence),
                    interpretation_type="inference",
                )
            )

        warnings = ["not_medical_advice", *context.warnings]
        return {
            "schema_version": "medical-insights-v1",
            "document_kind": context.document_kind,
            "language": context.language,
            "overview": {
                "title": context.title,
                "summary": summary,
                "study_type": _study_type(context.document_kind),
                "evidence_ids": [overview_item.evidence_id] if overview_item else [],
            },
            "key_findings": findings,
            "limitations": limitations,
            "medical_terms": [],
            "what_it_means": meanings,
            "what_it_does_not_mean": does_not_mean,
            "questions_for_professional": [
                "Which people were included in this document, and who was not included?",
                "How strong are the reported findings and their limitations?",
            ],
            "warnings": warnings,
        }


class FakeMedicalAIProvider:
    """Test provider that returns prepared payloads without a network call."""

    name = "fake"

    def __init__(
        self,
        payload: Any | None = None,
        payloads: list[Any] | None = None,
        model_name: str = "fake-v1",
    ) -> None:
        self.model_name = model_name
        self.payload = payload
        self.payloads = list(payloads or [])
        self.calls: list[tuple[str, AnalysisContext]] = []

    def generate(self, prompt: str, context: AnalysisContext) -> Any:
        self.calls.append((prompt, context))
        if self.payloads:
            return copy.deepcopy(self.payloads.pop(0))
        if self.payload is not None:
            return copy.deepcopy(self.payload)
        return ExtractiveMedicalAIProvider().generate(prompt, context)


def get_provider(name: str, model_name: str = "") -> MedicalAIProvider:
    provider_name = (name or "extractive").strip().lower()
    if provider_name == "extractive":
        return ExtractiveMedicalAIProvider(model_name or "extractive-v1")
    if provider_name == "fake":
        return FakeMedicalAIProvider(model_name=model_name or "fake-v1")
    raise ProviderUnavailable(
        f"Medical AI provider '{provider_name}' is not configured.",
        details={"provider": provider_name},
    )


def _first_of(evidence: list[EvidenceItem], *section_types: str) -> EvidenceItem | None:
    for section_type in section_types:
        item = next((item for item in evidence if item.section_type == section_type), None)
        if item:
            return item
    return None


def _take_distinct(
    evidence: list[EvidenceItem],
    section_types: set[str],
    *,
    limit: int,
) -> list[EvidenceItem]:
    result: list[EvidenceItem] = []
    seen: set[str] = set()
    for item in evidence:
        if item.section_type not in section_types:
            continue
        statement = _summary(item.text)
        if not statement or statement in seen:
            continue
        seen.add(statement)
        result.append(item)
        if len(result) >= limit:
            break
    return result


def _finding(
    finding_id: str,
    statement: str,
    explanation: str,
    item: EvidenceItem,
    *,
    interpretation_type: str,
) -> dict[str, Any]:
    return {
        "id": finding_id,
        "statement": statement,
        "plain_explanation": explanation,
        "evidence_ids": [item.evidence_id],
        "evidence_level": "reported_in_document",
        "interpretation_type": interpretation_type,
    }


def _item_for_finding(finding: dict[str, Any], evidence: list[EvidenceItem]) -> EvidenceItem:
    evidence_id = (finding.get("evidence_ids") or [""])[0]
    return next(item for item in evidence if item.evidence_id == evidence_id)


def _summary(text: str, max_chars: int = 360) -> str:
    normalized = " ".join(str(text or "").split())
    if not normalized:
        return ""
    match = re.search(r"[.!?。！？](?:\s|$)", normalized)
    if match and match.end() <= max_chars:
        return normalized[: match.end()].strip()
    if len(normalized) <= max_chars:
        return normalized
    shortened = normalized[:max_chars].rsplit(" ", 1)[0].rstrip(" ,;:")
    return f"{shortened}..."


def _study_type(document_kind: str) -> str:
    return {
        "research_paper": "Research paper",
        "guideline": "Clinical guideline or consensus document",
    }.get(document_kind, "Medical document")
