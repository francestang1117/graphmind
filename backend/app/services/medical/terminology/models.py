"""Typed records for the local medical disease ontology."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


AliasLanguage = Literal["en", "zh-Hans", "zh-Hant", "ja"]
AliasResolution = Literal["automatic", "confirmation_required", "blocked"]
MatchStatus = Literal["ready", "needs_confirmation"]
_COMMIT_SHA = re.compile(r"[0-9a-fA-F]{40}")


def validate_concept_identifiers(
    concept_id: str,
    mesh_id: str | None,
    orpha_code: str | None,
) -> None:
    """Reject concept records whose prefixed ID disagrees with its source ID."""
    if concept_id.startswith("mesh:"):
        expected = concept_id.removeprefix("mesh:")
        if not mesh_id:
            raise ValueError(f"{concept_id} must include mesh_id")
        if expected != mesh_id:
            raise ValueError(
                f"concept id {concept_id} does not match mesh_id {mesh_id}"
            )
    if concept_id.startswith("orpha:"):
        expected = concept_id.removeprefix("orpha:")
        if not orpha_code:
            raise ValueError(f"{concept_id} must include orpha_code")
        if expected != orpha_code:
            raise ValueError(
                f"concept id {concept_id} does not match orpha_code {orpha_code}"
            )


class ConceptSelection(BaseModel):
    """A user's explicit choice for one ambiguous alias match."""

    model_config = ConfigDict(extra="forbid")

    match_id: str = Field(min_length=8, max_length=64)
    concept_id: str = Field(min_length=1, max_length=160)


class DiseaseAlias(BaseModel):
    """One language-specific spelling of a disease concept."""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=200)
    language: AliasLanguage
    alias_type: str = Field(min_length=1, max_length=32)
    resolution: AliasResolution = "automatic"
    source: str = Field(min_length=1, max_length=80)

    @field_validator("text", "alias_type", "source")
    @classmethod
    def trim_values(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("terminology values must not be blank")
        return value


class DiseaseConcept(BaseModel):
    """A normalized disease and the safe PubMed clauses it can produce."""

    model_config = ConfigDict(extra="forbid")

    concept_id: str = Field(min_length=1, max_length=160)
    preferred_name_en: str = Field(min_length=1, max_length=200)
    preferred_name_zh: str = Field(default="", max_length=200)
    mesh_id: str | None = Field(default=None, max_length=64)
    orpha_code: str | None = Field(default=None, max_length=64)
    pubmed_terms: list[str] = Field(min_length=1, max_length=8)
    aliases: list[DiseaseAlias] = Field(min_length=1, max_length=100)

    @field_validator("concept_id", "preferred_name_en", "preferred_name_zh")
    @classmethod
    def trim_names(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def validate_identifiers(self) -> "DiseaseConcept":
        validate_concept_identifiers(
            self.concept_id,
            self.mesh_id,
            self.orpha_code,
        )
        return self


class OntologySource(BaseModel):
    """A source record kept in the manifest for auditability."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    license_url: str = Field(min_length=1, max_length=512)
    source_url: str = Field(default="", max_length=512)
    release: str = Field(default="", max_length=64)
    revision: str = Field(default="", max_length=64)
    file_sha256: str = Field(default="", max_length=64)
    file_name: str = Field(default="", max_length=255)

    @field_validator("file_sha256")
    @classmethod
    def validate_file_sha256(cls, value: str) -> str:
        if value and not re.fullmatch(r"[0-9a-fA-F]{64}", value):
            raise ValueError("source file checksum must be a SHA-256 digest")
        return value

    @field_validator("source_url")
    @classmethod
    def validate_source_url(cls, value: str) -> str:
        match = re.search(r"github\.com/[^/]+/[^/]+/blob/([^/]+)/", value)
        if match and not _COMMIT_SHA.fullmatch(match.group(1)):
            raise ValueError("GitHub source URLs must identify a commit SHA")
        return value

    @field_validator("revision")
    @classmethod
    def validate_revision(cls, value: str) -> str:
        if value and not _COMMIT_SHA.fullmatch(value):
            raise ValueError("source revision must be a 40-character commit SHA")
        return value


class OntologyManifest(BaseModel):
    """Integrity and provenance metadata for one immutable data package."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(ge=1, le=1)
    ontology_version: str = Field(min_length=1, max_length=64)
    source_revision: str = Field(default="", max_length=64)
    mesh_release: str = Field(default="", max_length=64)
    orphanet_release: str = Field(default="", max_length=64)
    generated_at: str = Field(min_length=1, max_length=64)
    data_file: str = Field(min_length=1, max_length=255)
    record_count: int = Field(ge=0)
    alias_count: int = Field(ge=0)
    sha256: str = Field(min_length=64, max_length=64)
    sources: list[OntologySource] = Field(min_length=1, max_length=20)

    @field_validator("source_revision")
    @classmethod
    def validate_source_revision(cls, value: str) -> str:
        if value and not _COMMIT_SHA.fullmatch(value):
            raise ValueError("source revision must be a 40-character commit SHA")
        return value


class DiseaseCandidate(BaseModel):
    """Safe display data for one candidate in an ambiguous match."""

    model_config = ConfigDict(extra="forbid")

    concept_id: str
    preferred_name: str
    display_name_zh: str = ""
    matched_alias: str
    resolution: AliasResolution
    mesh_id: str | None = None
    orpha_code: str | None = None


class DiseaseMatch(BaseModel):
    """One alias occurrence and its candidate concepts."""

    model_config = ConfigDict(extra="forbid")

    match_id: str = Field(min_length=8, max_length=64)
    matched_text: str = Field(min_length=1, max_length=200)
    normalized_text: str = Field(min_length=1, max_length=200)
    status: MatchStatus
    candidates: list[DiseaseCandidate] = Field(min_length=1, max_length=20)
