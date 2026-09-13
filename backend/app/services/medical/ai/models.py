"""Stable input and output shapes for document-level medical insights."""

from __future__ import annotations

from typing import Any, Literal, Self

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
QuestionSuggestionCategory = Literal[
    "clarify_finding",
    "applicability",
    "study_limitation",
    "evidence_gap",
    "monitoring_discussion",
    "research_option",
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


class QuestionSuggestion(_StrictModel):
    """A safe, source-backed question for discussion with a professional."""

    id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    question: str = Field(min_length=1, max_length=500)
    rationale: str = Field(min_length=1, max_length=1000)
    category: QuestionSuggestionCategory
    evidence_ids: list[str] = Field(min_length=1, max_length=5)
    interpretation_type: InterpretationType = "inference"


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
    schema_version: str = "medical-insights-v3"
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
    question_suggestions: list[QuestionSuggestion] = Field(default_factory=list, max_length=5)
    # Kept so previously saved V2 reports remain readable.
    questions_for_professional: list[str] = Field(default_factory=list)
    coverage: AnalysisCoverage = Field(default_factory=AnalysisCoverage)
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def infer_v2_for_unversioned_legacy_report(cls, data: Any) -> Any:
        """Keep reports written before schema_version was persisted readable."""
        if (
            isinstance(data, dict)
            and not data.get("schema_version")
            and data.get("questions_for_professional")
        ):
            data = dict(data)
            data["schema_version"] = "medical-insights-v2"
        return data

    @model_validator(mode="after")
    def validate_v3_legacy_questions(self) -> Self:
        if self.schema_version == "medical-insights-v3" and self.questions_for_professional:
            raise ValueError(
                "medical-insights-v3 reports must leave questions_for_professional empty"
            )
        return self
