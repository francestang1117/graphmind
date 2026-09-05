"""Small data objects shared by the medical analysis services."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class MedicalDocumentKind(str, Enum):
    RESEARCH_PAPER = "research_paper"
    GUIDELINE = "guideline"
    CLINICAL_REPORT = "clinical_report"
    LAB_REPORT = "lab_report"
    IMAGING_REPORT = "imaging_report"
    DISCHARGE_SUMMARY = "discharge_summary"
    PRESCRIPTION = "prescription"
    PATIENT_NOTE = "patient_note"
    OTHER_MEDICAL = "other_medical"
    UNKNOWN = "unknown"


class MedicalSectionType(str, Enum):
    TITLE = "title"
    ABSTRACT = "abstract"
    INTRODUCTION = "introduction"
    METHODS = "methods"
    POPULATION = "population"
    INTERVENTION = "intervention"
    COMPARATOR = "comparator"
    OUTCOMES = "outcomes"
    RESULTS = "results"
    ADVERSE_EVENTS = "adverse_events"
    DISCUSSION = "discussion"
    LIMITATIONS = "limitations"
    CONCLUSION = "conclusion"
    REFERENCES = "references"
    SUPPLEMENTARY = "supplementary"
    TABLE = "table"
    FIGURE_CAPTION = "figure_caption"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class AnalysisWarning:
    code: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass
class MedicalDocumentAnalysis:
    document_kind: str
    confidence: float
    language: str
    classifier_version: str
    signals: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    missing_sections: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_kind": self.document_kind,
            "confidence": round(float(self.confidence), 3),
            "language": self.language,
            "classifier_version": self.classifier_version,
            "signals": list(self.signals),
            "warnings": list(self.warnings),
            "missing_sections": list(self.missing_sections),
        }


@dataclass
class StructuredSection:
    section_type: str
    original_title: str
    ordinal: int
    page_start: int | None
    page_end: int | None
    char_start: int
    char_end: int
    text: str
    language: str
    confidence: float
    secondary_types: list[str] = field(default_factory=list)
    chunk_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "section_type": self.section_type,
            "original_title": self.original_title,
            "ordinal": self.ordinal,
            "page_start": self.page_start,
            "page_end": self.page_end,
            "char_start": self.char_start,
            "char_end": self.char_end,
            "text": self.text,
            "language": self.language,
            "confidence": round(float(self.confidence), 3),
            "secondary_types": list(self.secondary_types),
            "chunk_count": self.chunk_count,
            "metadata": dict(self.metadata),
        }


@dataclass
class PaperStructureResult:
    sections: list[StructuredSection] = field(default_factory=list)
    chunks: list[dict[str, Any]] = field(default_factory=list)
    missing_sections: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "sections": [section.to_dict() for section in self.sections],
            "chunks": list(self.chunks),
            "missing_sections": list(self.missing_sections),
            "warnings": list(self.warnings),
        }
