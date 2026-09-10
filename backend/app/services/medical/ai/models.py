"""Stable input and output shapes for document-level medical insights."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


InterpretationType = Literal[
    "direct_statement",
    "summary",
    "inference",
    "uncertain",
]
SupportStatus = Literal[
    "supported",
    "partially_supported",
    "not_reported",
    "uncertain",
]
NOT_REPORTED_VALUE = "Not reported in the selected source evidence."


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


class EvidenceAttribute(_StrictModel):
    value: str = NOT_REPORTED_VALUE
    support_status: SupportStatus = "not_reported"
    evidence_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_not_reported_state(self) -> Self:
        if self.support_status == "not_reported" and (
            self.value != NOT_REPORTED_VALUE or self.evidence_ids
        ):
            raise ValueError(
                "not_reported attributes must use the fixed missing-value text "
                "and cannot cite evidence"
            )
        return self


class StudyMethods(_StrictModel):
    design: EvidenceAttribute = Field(default_factory=EvidenceAttribute)
    population: EvidenceAttribute = Field(default_factory=EvidenceAttribute)
    human_animal_in_vitro: EvidenceAttribute = Field(default_factory=EvidenceAttribute)
    sample_size: EvidenceAttribute = Field(default_factory=EvidenceAttribute)
    comparator: EvidenceAttribute = Field(default_factory=EvidenceAttribute)


class AnalysisCoverage(_StrictModel):
    complete: bool = True
    selected_chunks: int = 0
    total_chunks: int = 0
    selected_tokens: int = 0
    max_input_tokens: int = 0
    included_sections: list[str] = Field(default_factory=list)
    omitted_sections: list[str] = Field(default_factory=list)


class MedicalInsightReport(_StrictModel):
    schema_version: str = "medical-insights-v2"
    document_kind: str
    language: str
    overview: DocumentOverview
    study_methods: StudyMethods = Field(default_factory=StudyMethods)
    key_findings: list[EvidenceFinding] = Field(default_factory=list)
    limitations: list[EvidenceFinding] = Field(default_factory=list)
    medical_terms: list[MedicalTermExplanation] = Field(default_factory=list)
    what_it_means: list[EvidenceFinding] = Field(default_factory=list)
    what_it_does_not_mean: list[EvidenceFinding] = Field(default_factory=list)
    applicability: list[EvidenceFinding] = Field(default_factory=list)
    future_research: list[EvidenceFinding] = Field(default_factory=list)
    questions_for_professional: list[str] = Field(default_factory=list)
    coverage: AnalysisCoverage = Field(default_factory=AnalysisCoverage)
    warnings: list[str] = Field(default_factory=list)
