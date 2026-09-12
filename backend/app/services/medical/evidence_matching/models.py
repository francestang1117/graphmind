"""Typed values returned by deterministic evidence matching."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


FindingType = Literal[
    "key_finding",
    "limitation",
    "meaning",
    "not_meaning",
    "applicability",
    "future_research",
]
FindingMatchStatus = Literal[
    "matched",
    "condition_only",
    "insufficient_terms",
    "no_candidates",
]
MatchSpecificity = Literal["finding_specific", "condition_only"]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MatchableFinding(_StrictModel):
    """A report finding that has enough provenance to be matched safely."""

    finding_id: str = Field(min_length=1, max_length=128)
    finding_type: FindingType
    statement: str = Field(min_length=1, max_length=8000)
    plain_explanation: str = Field(default="", max_length=8000)
    evidence_ids: list[str] = Field(default_factory=list, max_length=32)
    normalized_text: str = Field(min_length=1, max_length=8000)
    controlled_terms: list[str] = Field(default_factory=list, max_length=8)
    condition_terms: list[str] = Field(default_factory=list, max_length=16)
    biomedical_terms: list[str] = Field(default_factory=list, max_length=16)
    keywords: list[str] = Field(default_factory=list, max_length=10)
    phrases: list[str] = Field(default_factory=list, max_length=5)


class MatchFeature(_StrictModel):
    """One score contribution that can be shown to a user or auditor."""

    feature: str = Field(min_length=1, max_length=64)
    score: int = Field(ge=0, le=100)
    matched_values: list[str] = Field(default_factory=list, max_length=20)
    explanation: str = Field(min_length=1, max_length=500)


class StudyCard(_StrictModel):
    """A PubMed article summary without a claim about study quality or efficacy."""

    article_id: str = Field(min_length=1, max_length=64)
    source: Literal["pubmed"] = "pubmed"
    pmid: str = Field(min_length=1, max_length=128)
    doi: str | None = Field(default=None, max_length=255)
    pmcid: str | None = Field(default=None, max_length=64)
    title: str = Field(default="", max_length=4000)
    journal: str = Field(default="", max_length=1000)
    publication_year: int | None = Field(default=None, ge=1000, le=3000)
    publication_types: list[str] = Field(default_factory=list, max_length=100)
    study_category: str = Field(min_length=1, max_length=64)
    development_phase: str = Field(min_length=1, max_length=64)
    abstract_available: bool = False
    relevance_score: int = Field(ge=0, le=100)
    match_specificity: MatchSpecificity
    matched_terms: list[str] = Field(default_factory=list, max_length=30)
    match_reasons: list[str] = Field(default_factory=list, max_length=20)
    match_features: list[MatchFeature] = Field(default_factory=list, max_length=20)
    abstract_quote: str | None = Field(default=None, max_length=600)
    abstract_character_start: int | None = Field(default=None, ge=0)
    abstract_character_end: int | None = Field(default=None, ge=0)
    retraction_status: str = Field(default="unknown", max_length=32)
    source_url: str = Field(default="", max_length=512)
    warnings: list[str] = Field(default_factory=list, max_length=20)
    stale: bool = False


class FindingMatchResult(_StrictModel):
    """The candidates and explicit outcome for one finding snapshot."""

    finding: MatchableFinding
    match_status: FindingMatchStatus
    candidates: list[StudyCard] = Field(default_factory=list, max_length=5)


class LiteratureMatchResult(_StrictModel):
    """In-memory result before it is written by the repository."""

    findings: list[FindingMatchResult] = Field(default_factory=list, max_length=20)
    excluded_articles: dict[str, int] = Field(default_factory=dict, max_length=8)
    warnings: list[str] = Field(default_factory=list, max_length=20)
    empty_reason: str = Field(default="", max_length=64)
    article_count: int = Field(default=0, ge=0)
    match_count: int = Field(default=0, ge=0)


def model_dump_json_safe(value: Any) -> Any:
    """Return JSON-compatible data without allowing model internals to leak."""
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    return value
