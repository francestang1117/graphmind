"""Load and verify an immutable local disease ontology package."""

from __future__ import annotations

import gzip
import hashlib
import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Iterator

from app.services.medical.terminology.models import (
    DiseaseAlias,
    DiseaseConcept,
    OntologyManifest,
)
from app.services.medical.terminology.normalizer import normalize_terminology_text
from app.services.medical.terminology.pubmed_mapper import pubmed_terms_for_concept


class DiseaseOntologyError(RuntimeError):
    """Raised when the local terminology package cannot be trusted."""


@dataclass(frozen=True)
class _AliasBinding:
    concept: DiseaseConcept
    alias: DiseaseAlias
    normalized_alias: str


class DiseaseOntology:
    """Verified read-only terminology with normalized alias indexes."""

    def __init__(
        self,
        *,
        manifest: OntologyManifest,
        concepts: tuple[DiseaseConcept, ...],
        source_path: Path,
        data_sha256: str,
    ) -> None:
        self.manifest = manifest
        self.concepts = concepts
        self.source_path = source_path
        self.data_sha256 = data_sha256
        self._concepts_by_id = {concept.concept_id: concept for concept in concepts}
        bindings: dict[str, list[_AliasBinding]] = {}
        for concept in concepts:
            for alias in concept.aliases:
                normalized_alias = normalize_terminology_text(alias.text)
                bindings.setdefault(normalized_alias, []).append(
                    _AliasBinding(concept, alias, normalized_alias)
                )
        self._bindings = {
            key: tuple(sorted(value, key=lambda item: item.concept.concept_id))
            for key, value in bindings.items()
        }

    @property
    def version(self) -> str:
        return self.manifest.ontology_version

    def get(self, concept_id: str) -> DiseaseConcept | None:
        return self._concepts_by_id.get(concept_id)

    def alias_bindings(self) -> Iterator[tuple[str, tuple[_AliasBinding, ...]]]:
        """Yield normalized aliases and their candidate concepts."""
        return iter(self._bindings.items())

    @classmethod
    def from_directory(
        cls,
        directory: str | Path,
        *,
        verify_checksum: bool = True,
        require_nonempty: bool = True,
    ) -> "DiseaseOntology":
        resource_dir = Path(directory).expanduser().resolve()
        manifest_path = resource_dir / "manifest.json"
        if not manifest_path.is_file():
            raise DiseaseOntologyError("ontology manifest is missing")
        try:
            manifest = OntologyManifest.model_validate(
                json.loads(manifest_path.read_text(encoding="utf-8"))
            )
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            raise DiseaseOntologyError("ontology manifest is invalid") from exc

        data_path = (resource_dir / manifest.data_file).resolve()
        if resource_dir not in data_path.parents:
            raise DiseaseOntologyError("ontology data file escapes its resource directory")
        if not data_path.is_file():
            raise DiseaseOntologyError("ontology data file is missing")
        try:
            raw_data = data_path.read_bytes()
        except OSError as exc:
            raise DiseaseOntologyError("ontology data file cannot be read") from exc
        data_sha256 = hashlib.sha256(raw_data).hexdigest()
        if verify_checksum and data_sha256 != manifest.sha256.casefold():
            raise DiseaseOntologyError("ontology checksum does not match its manifest")

        concepts = tuple(_read_concepts(raw_data, data_path))
        if require_nonempty and not concepts:
            raise DiseaseOntologyError("ontology contains no concepts")
        if len(concepts) != manifest.record_count:
            raise DiseaseOntologyError("ontology record count does not match its manifest")
        alias_count = sum(len(concept.aliases) for concept in concepts)
        if alias_count != manifest.alias_count:
            raise DiseaseOntologyError("ontology alias count does not match its manifest")
        ids = [concept.concept_id for concept in concepts]
        if len(ids) != len(set(ids)):
            raise DiseaseOntologyError("ontology concept ids are not unique")
        for concept in concepts:
            if not normalize_terminology_text(concept.preferred_name_en):
                raise DiseaseOntologyError("ontology concept has a blank preferred name")
            try:
                pubmed_terms_for_concept(concept)
            except ValueError as exc:
                raise DiseaseOntologyError(
                    f"ontology concept {concept.concept_id} has an invalid PubMed term"
                ) from exc
            for alias in concept.aliases:
                if not normalize_terminology_text(alias.text):
                    raise DiseaseOntologyError("ontology contains a blank alias")
        return cls(
            manifest=manifest,
            concepts=concepts,
            source_path=data_path,
            data_sha256=data_sha256,
        )


def _read_concepts(raw_data: bytes, data_path: Path) -> Iterator[DiseaseConcept]:
    try:
        content = gzip.decompress(raw_data) if data_path.suffix == ".gz" else raw_data
        text = content.decode("utf-8")
    except (OSError, EOFError, UnicodeError) as exc:
        raise DiseaseOntologyError("ontology data is not valid UTF-8 gzip or JSONL") from exc
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
            yield DiseaseConcept.model_validate(value)
        except (json.JSONDecodeError, ValueError) as exc:
            raise DiseaseOntologyError(
                f"ontology record {line_number} is invalid"
            ) from exc


def get_default_ontology() -> DiseaseOntology:
    """Load the configured local package shipped with the application."""
    # Import settings lazily so the terminology package can still be used by
    # the ontology builder and isolated tests without an import cycle.
    from app.core.config import settings

    return _load_ontology(str(Path(settings.MEDICAL_ONTOLOGY_DIR).expanduser().resolve()))


@lru_cache(maxsize=4)
def _load_ontology(directory: str) -> DiseaseOntology:
    return DiseaseOntology.from_directory(directory)
