"""Privacy-bounded disease alias matching with explicit ambiguity handling."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
from typing import Iterable

from app.services.medical.terminology.loader import DiseaseOntology, _AliasBinding
from app.services.medical.terminology.models import (
    ConceptSelection,
    DiseaseCandidate,
    DiseaseConcept,
    DiseaseMatch,
)
from app.services.medical.terminology.normalizer import (
    normalize_match_text_with_spans,
    normalize_terminology_text,
)


class DiseaseMatchError(ValueError):
    """Raised when a submitted concept selection is not valid for the text."""


@dataclass(frozen=True)
class _RawMatch:
    start: int
    end: int
    alias: str
    binding: _AliasBinding


@dataclass(frozen=True)
class OntologyResolution:
    """The safe concepts and unresolved matches found in one question."""

    matches: tuple[DiseaseMatch, ...]
    selected_concepts: tuple[DiseaseConcept, ...]
    unresolved_matches: tuple[DiseaseMatch, ...]

    @property
    def needs_confirmation(self) -> bool:
        return bool(self.unresolved_matches)


class DiseaseMatcher:
    """Match exact local aliases; never infer an unknown disease name."""

    def __init__(self, ontology: DiseaseOntology) -> None:
        self.ontology = ontology

    def resolve(
        self,
        text: str,
        selections: Iterable[ConceptSelection] | None = None,
    ) -> OntologyResolution:
        submitted_selections = tuple(selections or ())
        if len({selection.match_id for selection in submitted_selections}) != len(
            submitted_selections
        ):
            raise DiseaseMatchError("concept selection contains duplicate match ids")
        selection_map = {
            selection.match_id: selection.concept_id
            for selection in submitted_selections
        }
        matches = self.find_matches(text)
        match_ids = {match.match_id for match in matches}
        unknown_selection_ids = set(selection_map) - match_ids
        if unknown_selection_ids:
            raise DiseaseMatchError("concept selection does not belong to this question")

        selected: list[DiseaseConcept] = []
        unresolved: list[DiseaseMatch] = []
        for match in matches:
            selected_id = selection_map.get(match.match_id)
            candidate_ids = {candidate.concept_id for candidate in match.candidates}
            if selected_id is not None and selected_id not in candidate_ids:
                raise DiseaseMatchError("concept selection is not a candidate for this match")
            if any(candidate.resolution == "blocked" for candidate in match.candidates):
                raise DiseaseMatchError("this disease alias cannot be used safely")
            if match.status == "needs_confirmation" and selected_id is None:
                unresolved.append(match)
                continue
            concept_id = selected_id or match.candidates[0].concept_id
            concept = self.ontology.get(concept_id)
            if concept is not None and concept.concept_id not in {item.concept_id for item in selected}:
                selected.append(concept)
        return OntologyResolution(
            matches=tuple(matches),
            selected_concepts=tuple(selected),
            unresolved_matches=tuple(unresolved),
        )

    def find_matches(self, text: str) -> list[DiseaseMatch]:
        normalized_text, source_spans = normalize_match_text_with_spans(text)
        if not normalized_text:
            return []
        raw_matches: list[_RawMatch] = []
        aliases = sorted(
            self.ontology.alias_bindings(),
            key=lambda item: (-len(item[0]), item[0]),
        )
        for normalized_alias, bindings in aliases:
            pattern = _alias_pattern(normalized_alias)
            for occurrence in pattern.finditer(normalized_text):
                for binding in bindings:
                    raw_matches.append(
                        _RawMatch(
                            start=occurrence.start(),
                            end=occurrence.end(),
                            alias=normalized_alias,
                            binding=binding,
                        )
                    )

        accepted: list[list[_RawMatch]] = []
        for candidate in sorted(
            raw_matches,
            key=lambda item: (item.start, -(item.end - item.start), item.binding.concept.concept_id),
        ):
            same_span = next(
                (group for group in accepted if group[0].start == candidate.start and group[0].end == candidate.end),
                None,
            )
            if same_span is not None:
                if all(
                    item.binding.concept.concept_id != candidate.binding.concept.concept_id
                    for item in same_span
                ):
                    same_span.append(candidate)
                continue
            if any(
                candidate.start < group[0].end and candidate.end > group[0].start
                for group in accepted
            ):
                continue
            accepted.append([candidate])

        result: list[DiseaseMatch] = []
        for group in sorted(accepted, key=lambda item: item[0].start):
            first = group[0]
            candidate_by_id: dict[str, DiseaseCandidate] = {}
            for item in group:
                concept = item.binding.concept
                candidate_by_id.setdefault(
                    concept.concept_id,
                    DiseaseCandidate(
                        concept_id=concept.concept_id,
                        preferred_name=concept.preferred_name_en,
                        display_name_zh=concept.preferred_name_zh,
                        matched_alias=item.binding.alias.text,
                        resolution=item.binding.alias.resolution,
                        mesh_id=concept.mesh_id,
                        orpha_code=concept.orpha_code,
                    ),
                )
            candidates = sorted(candidate_by_id.values(), key=lambda item: item.concept_id)
            source_start = source_spans[first.start][0]
            source_end = source_spans[first.end - 1][1]
            match_text = str(text)[source_start:source_end]
            status = (
                "needs_confirmation"
                if len(candidates) > 1
                or any(candidate.resolution != "automatic" for candidate in candidates)
                else "ready"
            )
            result.append(
                DiseaseMatch(
                    match_id=_match_id(self.ontology.version, normalized_text, first.start, first.end),
                    matched_text=match_text,
                    normalized_text=normalize_terminology_text(match_text),
                    status=status,
                    candidates=candidates,
                )
            )
        return result


def _alias_pattern(alias: str) -> re.Pattern[str]:
    if re.search(r"[a-z]", alias):
        return re.compile(
            r"(?<![a-z0-9])" + re.escape(alias) + r"(?![a-z0-9])",
            flags=re.IGNORECASE,
        )
    return re.compile(re.escape(alias))


def _match_id(version: str, text: str, start: int, end: int) -> str:
    value = f"{version}:{start}:{end}:{text[start:end]}"
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]
