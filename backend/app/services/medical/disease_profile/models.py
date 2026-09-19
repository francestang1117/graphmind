"""Stable API models for workspace-scoped disease research profiles."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


ProfileSection = Literal[
    "key_findings",
    "study_methods",
    "limitations",
    "what_it_means",
    "what_it_does_not_mean",
    "applicability",
    "future_research",
    "medical_terms",
    "clinician_questions",
    "external_studies",
]

LinkSource = Literal["manual_selection", "confirmed_search"]
ProfileSourceStatus = Literal["current", "outdated", "unavailable"]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DocumentDiseaseLink(_StrictModel):
    """A persisted association with ontology names captured at link time."""

    id: str
    document_id: str
    concept_id: str
    preferred_name_en: str
    preferred_name_zh: str = ""
    matched_alias: str = ""
    ontology_version: str
    link_source: LinkSource
    source_search_run_id: str | None = None
    created_at: str
    updated_at: str


class DiseaseProfileSource(_StrictModel):
    """One quote or a public article source shown beneath an aggregate item."""

    source_type: Literal["document_evidence", "external_article"]
    evidence_id: str | None = None
    document_id: str | None = None
    document_title: str = ""
    document_date: str = ""
    analysis_run_id: str | None = None
    parsed_source_hash: str = ""
    section_type: str = "unknown"
    section_title: str = ""
    page_start: int | None = None
    page_end: int | None = None
    quote: str = ""
    source: str = ""
    external_id: str = ""
    source_url: str = ""
    retraction_status: str = "unknown"
    flagged: bool = False
    warnings: list[str] = Field(default_factory=list, max_length=20)


class DiseaseProfileItem(_StrictModel):
    """A deliberately unmerged finding, attribute, question, term, or article."""

    id: str
    item_type: Literal["finding", "attribute", "term", "question", "article"]
    section: ProfileSection
    document_id: str | None = None
    document_ids: list[str] = Field(default_factory=list, max_length=20)
    document_title: str = ""
    document_titles: list[str] = Field(default_factory=list, max_length=20)
    related_document_count: int = Field(default=0, ge=0)
    related_documents_truncated: bool = False
    document_kind: str = ""
    document_date: str = ""
    analysis_run_id: str | None = None
    parsed_source_hash: str = ""
    source_status: ProfileSourceStatus = "current"
    title: str = ""
    text: str = ""
    explanation: str = ""
    value: str = ""
    support_status: str = ""
    term: str = ""
    question: str = ""
    rationale: str = ""
    category: str = ""
    topic: str = ""
    source_kind: str = ""
    source_id: str = ""
    evidence_ids: list[str] = Field(default_factory=list, max_length=5)
    evidence: list[DiseaseProfileSource] = Field(default_factory=list, max_length=5)
    source: str = ""
    external_id: str = ""
    doi: str | None = None
    pmcid: str | None = None
    journal: str = ""
    publication_date: str | None = None
    publication_year: int | None = None
    publication_types: list[str] = Field(default_factory=list, max_length=100)
    source_url: str = ""
    retraction_status: str = "unknown"
    flagged: bool = False
    warnings: list[str] = Field(default_factory=list, max_length=20)
    relevance_score: float | None = None
    match_specificity: str = ""


class DiseaseProfileSection(_StrictModel):
    section: ProfileSection
    count: int = Field(ge=0)
    items: list[DiseaseProfileItem] = Field(default_factory=list, max_length=5)


class DiseaseProfileStats(_StrictModel):
    document_count: int = Field(ge=0)
    research_paper_count: int = Field(ge=0)
    guideline_count: int = Field(ge=0)
    other_medical_document_count: int = Field(ge=0)
    valid_analysis_count: int = Field(ge=0)
    expired_analysis_count: int = Field(ge=0)
    external_article_count: int = Field(ge=0)
    flagged_article_count: int = Field(ge=0)
    comparator_reported_count: int = Field(ge=0)
    comparator_not_reported_count: int = Field(ge=0)
    human_study_count: int = Field(ge=0)
    animal_study_count: int = Field(ge=0)
    in_vitro_study_count: int = Field(ge=0)
    unknown_study_population_count: int = Field(ge=0)
    sample_size_reported_count: int = Field(ge=0)
    sample_size_not_reported_count: int = Field(ge=0)
    unknown_date_count: int = Field(ge=0)


class DiseaseProfileSummary(_StrictModel):
    concept_id: str
    preferred_name_en: str
    preferred_name_zh: str = ""
    ontology_version: str
    document_count: int = Field(ge=0)
    analysis_count: int = Field(ge=0)
    external_article_count: int = Field(ge=0)
    saved_question_count: int = Field(ge=0)
    last_updated_at: str = ""
    section_counts: dict[str, int] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list, max_length=20)


class DiseaseProfileDocument(_StrictModel):
    """A linked document summary used for source management in the UI."""

    document_id: str
    title: str
    document_kind: str = "unknown"
    language: str = "unknown"
    document_date: str = ""
    parsed_source_hash: str = ""
    source_status: ProfileSourceStatus = "unavailable"
    warnings: list[str] = Field(default_factory=list, max_length=20)


class DiseaseProfileDetail(DiseaseProfileSummary):
    stats: DiseaseProfileStats
    documents: list[DiseaseProfileDocument] = Field(default_factory=list, max_length=20)
    documents_next_cursor: str | None = None
    sections: list[DiseaseProfileSection] = Field(default_factory=list)


class DiseaseProfileListView(_StrictModel):
    items: list[DiseaseProfileSummary]
    next_cursor: str | None = None


class DiseaseProfileItemsView(_StrictModel):
    section: ProfileSection
    items: list[DiseaseProfileItem]
    next_cursor: str | None = None
    truncated: bool = False


class DiseaseProfileDocumentsView(_StrictModel):
    items: list[DiseaseProfileDocument] = Field(default_factory=list, max_length=50)
    next_cursor: str | None = None


class UnassignedDocumentView(_StrictModel):
    document_id: str
    title: str
    document_kind: str
    language: str
    document_date: str = ""
    medical_confidence: float = Field(ge=0, le=1)
    classifier_version: str = ""
    warnings: list[str] = Field(default_factory=list, max_length=20)


class DiseaseConceptOption(_StrictModel):
    concept_id: str
    preferred_name_en: str
    preferred_name_zh: str = ""
    ontology_version: str
    matched_alias: str = ""


class DiseaseConceptSearchView(_StrictModel):
    items: list[DiseaseConceptOption]


class UnassignedDocumentListView(_StrictModel):
    items: list[UnassignedDocumentView] = Field(default_factory=list, max_length=50)
    total: int = Field(default=0, ge=0)
    next_cursor: str | None = None
