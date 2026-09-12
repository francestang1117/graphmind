"""Exact-match and ambiguity behavior for local disease terminology."""

import pytest

from app.services.medical.terminology import DiseaseMatcher, get_default_ontology
from app.services.medical.terminology.matcher import DiseaseMatchError
from app.services.medical.terminology.models import ConceptSelection


def test_matcher_uses_longest_alias_and_preserves_display_text() -> None:
    matcher = DiseaseMatcher(get_default_ontology())
    matches = matcher.find_matches("Please review Duchenne Muscular Dystrophy.")

    assert len(matches) == 1
    assert matches[0].matched_text == "Duchenne Muscular Dystrophy"
    assert matches[0].candidates[0].preferred_name == "Duchenne Muscular Dystrophy"


def test_matcher_does_not_match_short_alias_inside_another_word() -> None:
    matcher = DiseaseMatcher(get_default_ontology())

    assert matcher.find_matches("regular software release") == []
    assert matcher.find_matches("glaucoma")


def test_confirmation_required_alias_has_no_automatic_resolution() -> None:
    matcher = DiseaseMatcher(get_default_ontology())
    preview = matcher.resolve("ALS")

    assert preview.needs_confirmation is True
    match = preview.unresolved_matches[0]
    selection = ConceptSelection(
        match_id=match.match_id,
        concept_id=match.candidates[0].concept_id,
    )
    resolved = matcher.resolve("ALS", [selection])

    assert resolved.needs_confirmation is False
    assert resolved.selected_concepts[0].preferred_name_en == "Amyotrophic Lateral Sclerosis"


def test_selection_must_belong_to_the_exact_match() -> None:
    matcher = DiseaseMatcher(get_default_ontology())

    with pytest.raises(DiseaseMatchError, match="does not belong"):
        matcher.resolve(
            "ALS",
            [ConceptSelection(match_id="not-a-real-match", concept_id="mesh:D000690")],
        )
