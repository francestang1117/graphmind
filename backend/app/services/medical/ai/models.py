"""Stable input and output shapes for document-level medical insights."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


InterpretationType = Literal[
    "direct_statement",
    "summary",
    "inference",
    "uncertain",
]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DocumentOverview(_StrictModel):
    title: str = ""
    summary: str
    study_type: str = ""
    evidence_ids: list[str] = Field(default_factory=list)


class EvidenceFinding(_StrictModel):
    id: str
    statement: str
    plain_explanation: str
    evidence_ids: list[str] = Field(default_factory=list)
    evidence_level: str = "reported_in_document"
    interpretation_type: InterpretationType = "summary"


class MedicalTermExplanation(_StrictModel):
    term: str
    explanation: str
    evidence_ids: list[str] = Field(default_factory=list)


class MedicalInsightReport(_StrictModel):
    schema_version: str = "medical-insights-v1"
    document_kind: str
    language: str
    overview: DocumentOverview
    key_findings: list[EvidenceFinding] = Field(default_factory=list)
    limitations: list[EvidenceFinding] = Field(default_factory=list)
    medical_terms: list[MedicalTermExplanation] = Field(default_factory=list)
    what_it_means: list[EvidenceFinding] = Field(default_factory=list)
    what_it_does_not_mean: list[EvidenceFinding] = Field(default_factory=list)
    questions_for_professional: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
