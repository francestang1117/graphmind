"""Small typed objects shared by the literature search pipeline."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


LiteratureSort = Literal["relevance", "newest"]
RetractionStatus = Literal["normal", "retracted", "corrected", "unknown"]


class DetectedConcept(BaseModel):
    """A safe, explainable term that can be included in an external query."""

    type: str
    original: str
    normalized: str


class LiteratureQuery(BaseModel):
    """The complete, already-normalized PubMed request."""

    question: str = Field(min_length=1, max_length=500)
    sanitized_question: str = Field(default="", max_length=500)
    redacted_fields: list[str] = Field(default_factory=list, max_length=8)
    normalized_query: str = Field(min_length=1, max_length=4000)
    detected_concepts: list[DetectedConcept] = Field(default_factory=list)
    date_from: date | None = None
    date_to: date | None = None
    study_types: list[str] = Field(default_factory=list, max_length=8)
    sort: LiteratureSort = "relevance"
    max_results: int = Field(default=20, ge=1, le=50)
    provider: str = "pubmed"
    query_hash: str = Field(min_length=64, max_length=64)


class LiteratureArticle(BaseModel):
    """Metadata normalized from one PubMed record."""

    source: str = "pubmed"
    external_id: str = Field(min_length=1, max_length=32)
    doi: str | None = Field(default=None, max_length=512)
    pmcid: str | None = Field(default=None, max_length=32)
    title: str = Field(default="", max_length=4000)
    abstract: str | None = None
    journal: str = Field(default="", max_length=1000)
    publication_date: str | None = Field(default=None, max_length=32)
    publication_year: int | None = Field(default=None, ge=1000, le=3000)
    authors: list[str] = Field(default_factory=list, max_length=500)
    publication_types: list[str] = Field(default_factory=list, max_length=100)
    mesh_terms: list[str] = Field(default_factory=list, max_length=500)
    language: str = Field(default="unknown", max_length=32)
    source_url: str = Field(default="", max_length=512)
    retraction_status: RetractionStatus = "unknown"
    metadata_hash: str = Field(min_length=64, max_length=64)
    fetched_at: datetime


class LiteratureSearchPage(BaseModel):
    """One provider response after ESearch and batch EFetch."""

    articles: list[LiteratureArticle] = Field(default_factory=list)
    total_count: int = Field(default=0, ge=0)
    fetched_at: datetime
    warnings: list[str] = Field(default_factory=list)
