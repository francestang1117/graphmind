"""Stable API models for workspace-scoped disease research profiles."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


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
ComparisonCoverageStatus = Literal["complete", "partial", "unknown"]
ComparisonSupportStatus = Literal[
    "supported",
    "partially_supported",
    "not_reported",
    "uncertain",
    "source_unavailable",
]
ComparisonLanguage = Literal["en", "zh", "ja"]


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
    evidence_total: int = Field(default=0, ge=0)
    evidence_truncated: bool = False
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
    current_analysis_run_id: str | None = None
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


class ComparisonDocumentSelection(_StrictModel):
    """One selected source and the current analysis versions seen by the client."""

    document_id: str = Field(min_length=1, max_length=255)
    expected_parsed_source_hash: str = Field(min_length=1, max_length=128)
    expected_analysis_run_id: str = Field(min_length=1, max_length=64)


class ComparisonPreviewRequest(_StrictModel):
    """Strict input contract for a bounded, read-only comparison preview."""

    documents: list[ComparisonDocumentSelection] = Field(
        min_length=2,
        max_length=5,
    )
    language: ComparisonLanguage = "en"

    @model_validator(mode="after")
    def validate_unique_documents(self) -> Self:
        document_ids = [item.document_id for item in self.documents]
        if len(document_ids) != len(set(document_ids)):
            raise ValueError("comparison documents must be unique")
        return self


class ComparisonEvidence(_StrictModel):
    """A quote tied to one analysis run and one selected document."""

    document_id: str = Field(min_length=1, max_length=255)
    analysis_run_id: str = Field(min_length=1, max_length=64)
    evidence_id: str = Field(min_length=1, max_length=128)
    quote: str = Field(min_length=1, max_length=5000)
    section_type: str = "unknown"
    section_title: str = ""
    page_start: int | None = Field(default=None, ge=1)
    page_end: int | None = Field(default=None, ge=1)
    quote_truncated: bool = False


class ComparisonMethod(_StrictModel):
    """One of the five fixed method fields shown by the comparison UI."""

    value: str = ""
    support_status: ComparisonSupportStatus = "not_reported"
    evidence: list[ComparisonEvidence] = Field(default_factory=list, max_length=5)
    evidence_total: int = Field(default=0, ge=0)
    evidence_truncated: bool = False
    warnings: list[str] = Field(default_factory=list, max_length=10)
    missing_reason: str = "not_extracted_from_analyzed_text"


class ComparisonMethods(_StrictModel):
    design: ComparisonMethod = Field(default_factory=ComparisonMethod)
    population: ComparisonMethod = Field(default_factory=ComparisonMethod)
    human_animal_in_vitro: ComparisonMethod = Field(default_factory=ComparisonMethod)
    sample_size: ComparisonMethod = Field(default_factory=ComparisonMethod)
    comparator: ComparisonMethod = Field(default_factory=ComparisonMethod)


class ComparisonCoverage(_StrictModel):
    status: ComparisonCoverageStatus = "unknown"
    selected_chunks: int = Field(default=0, ge=0)
    total_chunks: int = Field(default=0, ge=0)
    included_sections: list[str] = Field(default_factory=list, max_length=100)
    omitted_sections: list[str] = Field(default_factory=list, max_length=100)


class ComparisonFinding(_StrictModel):
    id: str = Field(min_length=1, max_length=200)
    statement: str = Field(min_length=1, max_length=5000)
    explanation: str = ""
    evidence: list[ComparisonEvidence] = Field(default_factory=list, max_length=5)
    evidence_total: int = Field(default=0, ge=0)
    evidence_truncated: bool = False
    warnings: list[str] = Field(default_factory=list, max_length=10)


class ComparisonQuestion(_StrictModel):
    id: str = Field(min_length=1, max_length=100)
    question: str = Field(min_length=1, max_length=500)
    rationale: str = ""
    document_id: str = Field(min_length=1, max_length=255)
    document_ids: list[str] = Field(default_factory=list, max_length=5)
    analysis_run_ids: list[str] = Field(default_factory=list, max_length=5)
    topic: str = ""
    evidence: list[ComparisonEvidence] = Field(default_factory=list, max_length=5)
    evidence_total: int = Field(default=0, ge=0)
    evidence_truncated: bool = False


class ComparisonDocument(_StrictModel):
    """One document's bounded, evidence-preserving comparison view."""

    document_id: str = Field(min_length=1, max_length=255)
    title: str
    document_kind: str = "unknown"
    document_date: str = ""
    open_filename: str = Field(min_length=1, max_length=255)
    analysis_run_id: str = Field(min_length=1, max_length=64)
    parsed_source_hash: str = Field(min_length=1, max_length=128)
    coverage_status: ComparisonCoverageStatus = "unknown"
    coverage: ComparisonCoverage = Field(default_factory=ComparisonCoverage)
    methods: ComparisonMethods = Field(default_factory=ComparisonMethods)
    findings: list[ComparisonFinding] = Field(default_factory=list, max_length=10)
    findings_total: int = Field(default=0, ge=0)
    findings_truncated: bool = False
    limitations: list[ComparisonFinding] = Field(default_factory=list, max_length=10)
    limitations_total: int = Field(default=0, ge=0)
    limitations_truncated: bool = False


class ComparisonPreview(_StrictModel):
    """Read-only comparison response in the exact requested document order."""

    concept_id: str = Field(min_length=1, max_length=255)
    documents: list[ComparisonDocument] = Field(min_length=2, max_length=5)
    discussion_questions: list[ComparisonQuestion] = Field(default_factory=list, max_length=3)
    warnings: list[str] = Field(default_factory=list, max_length=20)


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
