"""Stable schemas for saved clinician questions and visit briefs."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


QuestionStatus = Literal["saved", "asked", "answered", "dismissed"]
QuestionSourceStatus = Literal["current", "outdated", "unavailable"]
VisitBriefStatus = Literal["active"]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ClinicianQuestionEvidenceView(_StrictModel):
    evidence_id: str
    chunk_id: str | None = None
    section_id: str | None = None
    section_type: str
    section_title: str
    page_start: int | None = None
    page_end: int | None = None
    quote: str
    character_start: int | None = None
    character_end: int | None = None


class ClinicianQuestionView(_StrictModel):
    id: str
    workspace_id: str
    document_id: str
    document_title: str
    analysis_run_id: str
    suggestion_id: str
    question: str
    rationale: str
    category: str
    topic: str
    source_kind: str
    source_id: str
    evidence_ids: list[str] = Field(default_factory=list, max_length=5)
    language: str
    status: QuestionStatus
    priority: int = Field(ge=1, le=3)
    position: int = Field(ge=0)
    user_note: str = Field(default="", max_length=2000)
    version: int = Field(ge=1)
    source_status: QuestionSourceStatus
    evidence: list[ClinicianQuestionEvidenceView] = Field(default_factory=list, max_length=5)
    created_at: str
    updated_at: str


class ClinicianQuestionListView(_StrictModel):
    items: list[ClinicianQuestionView]
    total: int = Field(ge=0)


class VisitBriefEvidenceView(_StrictModel):
    evidence_id: str
    chunk_id: str | None = None
    section_id: str | None = None
    section_type: str
    section_title: str
    page_start: int | None = None
    page_end: int | None = None
    quote: str
    character_start: int | None = None
    character_end: int | None = None


class VisitBriefItemView(_StrictModel):
    id: str
    clinician_question_id: str
    document_id: str
    analysis_run_id: str
    position: int = Field(ge=0)
    question: str
    rationale: str
    user_note: str = ""
    evidence: list[VisitBriefEvidenceView] = Field(default_factory=list, max_length=5)


class VisitBriefView(_StrictModel):
    id: str
    workspace_id: str
    status: VisitBriefStatus
    language: str
    generated_at: str
    data_cutoff_at: str
    disclaimer: str
    items: list[VisitBriefItemView] = Field(min_length=1, max_length=10)


class VisitBriefListView(_StrictModel):
    items: list[VisitBriefView]
    total: int = Field(ge=0)
