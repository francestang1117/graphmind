"""Unit tests for the explainable and privacy-bounded query builder."""

from datetime import date

import pytest

from app.services.medical.literature.exceptions import LiteratureQueryError
from app.services.medical.literature.query_builder import (
    build_literature_query,
    redact_sensitive_text,
)
from app.services.medical.terminology.models import ConceptSelection
from app.services.medical.terminology.loader import DiseaseOntology, get_default_ontology


def test_build_query_extracts_known_concepts_and_filters() -> None:
    query = build_literature_query(
        "What is known about Fabry disease and renal function?",
        date_from=date(2018, 1, 1),
        date_to=date(2025, 12, 31),
        study_types=["systematic review", "randomized controlled trial"],
        sort="newest",
        max_results=12,
    )

    assert {item.normalized for item in query.detected_concepts} >= {
        "Fabry disease",
        "renal function",
    }
    assert '"Fabry Disease"[MeSH Terms]' in query.normalized_query
    assert '"Systematic Review"[Publication Type]' in query.normalized_query
    assert '"2018-01-01"[Date - Publication]' in query.normalized_query
    assert len(query.query_hash) == 64


def test_build_query_redacts_direct_identifiers_before_external_terms() -> None:
    query = build_literature_query(
        "For patient P12345 born 2020-04-03, contact me at test@example.com; "
        "what is known about diabetes treatment?"
    )

    assert "test@example.com" not in query.question
    assert "2020-04-03" not in query.question
    assert "P12345" not in query.question
    assert "email" in query.redacted_fields
    assert "date" in query.redacted_fields
    assert "record_id" in query.redacted_fields
    assert "test@example.com" not in query.normalized_query


def test_redaction_does_not_treat_normal_patient_phrases_as_record_ids() -> None:
    cleaned, redactions = redact_sensitive_text("Patient outcomes should be reported.")

    assert cleaned == "Patient outcomes should be reported."
    assert redactions == []


@pytest.mark.parametrize(
    ("question", "expected_term", "leaked_values"),
    [
        (
            "关于李明戈谢病有什么新研究？",
            "Gaucher disease",
            ("关于", "李明"),
        ),
        (
            "病例为李明戈谢病，有什么研究？",
            "Gaucher disease",
            ("病例", "李明"),
        ),
        (
            "患者张三患有戈谢病，有什么新研究？",
            "Gaucher disease",
            ("患者", "张三"),
        ),
        (
            "John Smith has Gaucher disease",
            "Gaucher disease",
            ("John", "Smith", "has"),
        ),
    ],
)
def test_dictionary_disease_query_keeps_only_the_normalized_term(
    question: str, expected_term: str, leaked_values: tuple[str, ...]
) -> None:
    query = build_literature_query(question)

    assert [concept.normalized for concept in query.detected_concepts] == [expected_term]
    for leaked_value in leaked_values:
        assert leaked_value.casefold() not in query.normalized_query.casefold()


@pytest.mark.parametrize(
    ("question", "expected_term"),
    [
        ("关于胃癌的最新研究", "Stomach cancer"),
        ("关于肝癌的治疗研究", "Liver cancer"),
        ("关于脑炎的研究", "Encephalitis"),
        ("关于麻疹的研究", "Measles"),
        ("关于痛风的研究", "Gout"),
    ],
)
def test_common_chinese_diseases_use_dictionary_terms(
    question: str, expected_term: str
) -> None:
    query = build_literature_query(question)

    assert [concept.normalized for concept in query.detected_concepts] == [expected_term]


@pytest.mark.parametrize(
    "question",
    [
        "关于李明未知病有什么新研究？",
        "病例为李明青龙病，有什么研究？",
    ],
)
def test_unrecognized_chinese_disease_text_fails_closed(question: str) -> None:
    with pytest.raises(LiteratureQueryError, match="No medical concepts"):
        build_literature_query(question)


def test_unrecognized_chinese_disease_is_not_hidden_by_a_legacy_concept() -> None:
    with pytest.raises(LiteratureQueryError, match="No medical concepts"):
        build_literature_query("关于青龙病和肾功能的研究")


def test_glaucoma_is_resolved_by_the_disease_ontology() -> None:
    query = build_literature_query("What treatments exist for glaucoma?")

    assert [concept.normalized for concept in query.detected_concepts] == ["Glaucoma"]
    assert "glaucoma[Title/Abstract]" in query.normalized_query


def test_short_gene_alias_does_not_match_an_english_substring() -> None:
    with pytest.raises(LiteratureQueryError, match="No medical concepts"):
        build_literature_query("What is a regular software release?")


@pytest.mark.parametrize(
    ("question", "expected_term"),
    [
        ("What is known about Huntington disease?", "Huntington Disease"),
        ("What is known about melanoma?", "Melanoma"),
        ("What is known about sarcoidosis?", "Sarcoidosis"),
        ("What is known about Duchenne muscular dystrophy?", "Duchenne Muscular Dystrophy"),
        ("关于亨廷顿病的治疗研究", "Huntington Disease"),
        ("关于黑色素瘤的治疗研究", "Melanoma"),
        ("关于结节病的研究", "Sarcoidosis"),
        ("关于杜氏肌营养不良的研究", "Duchenne Muscular Dystrophy"),
    ],
)
def test_rare_disease_aliases_use_local_standard_terms(
    question: str, expected_term: str
) -> None:
    query = build_literature_query(question)

    assert [concept.normalized for concept in query.detected_concepts] == [expected_term]
    assert all(concept.source == "local_ontology" for concept in query.detected_concepts)
    assert all(concept.ontology_version == query.ontology_version for concept in query.detected_concepts)
    assert "关于" not in query.normalized_query


def test_longest_chinese_alias_wins_over_generic_alias() -> None:
    query = build_literature_query("杜氏肌营养不良有哪些研究？")

    assert [concept.normalized for concept in query.detected_concepts] == [
        "Duchenne Muscular Dystrophy"
    ]


def test_ambiguous_abbreviation_requires_selection_before_query_generation() -> None:
    preview = build_literature_query("What is known about ALS?")

    assert preview.resolution_status == "needs_confirmation"
    assert preview.query_hash is None
    assert preview.normalized_query == ""
    assert preview.ambiguous_concepts[0].matched_text == "ALS"
    match = preview.ambiguous_concepts[0]
    selection = ConceptSelection(
        match_id=match.match_id,
        concept_id=match.candidates[0].concept_id,
    )

    resolved = build_literature_query(
        "What is known about ALS?",
        concept_selections=[selection],
    )

    assert resolved.resolution_status == "ready"
    assert resolved.query_hash is not None
    assert "Amyotrophic Lateral Sclerosis" in resolved.normalized_query
    assert "ALS[Title/Abstract]" not in resolved.normalized_query


def test_invalid_concept_selection_is_rejected() -> None:
    preview = build_literature_query("What is known about ALS?")

    with pytest.raises(LiteratureQueryError, match="selected disease concept"):
        build_literature_query(
            "What is known about ALS?",
            concept_selections=[
                ConceptSelection(
                    match_id=preview.ambiguous_concepts[0].match_id,
                    concept_id="mesh:not-a-candidate",
                )
            ],
        )


def test_ontology_version_and_selection_change_the_query_fingerprint() -> None:
    ontology = get_default_ontology()
    alternate = DiseaseOntology(
        manifest=ontology.manifest.model_copy(
            update={"ontology_version": "curated-seed-test"}
        ),
        concepts=ontology.concepts,
        source_path=ontology.source_path,
        data_sha256=ontology.data_sha256,
    )
    first = build_literature_query("What is known about Fabry disease?", ontology=ontology)
    second = build_literature_query(
        "What is known about Fabry disease?", ontology=alternate
    )

    assert first.ontology_version
    assert first.selected_concept_ids
    assert first.query_hash != second.query_hash


@pytest.mark.parametrize("question", ["What is known about GLA gene?", "What is GLA mutation?"])
def test_bare_gene_symbol_requires_a_word_boundary(question: str) -> None:
    query = build_literature_query(question)

    assert [concept.normalized for concept in query.detected_concepts] == ["GLA"]
    assert '"GLA"[Title/Abstract]' in query.normalized_query


def test_build_query_rejects_unsupported_or_uninformative_questions() -> None:
    with pytest.raises(LiteratureQueryError, match="No medical concepts"):
        build_literature_query("How should I organize my software project?")

    with pytest.raises(LiteratureQueryError, match="date range"):
        build_literature_query(
            "What is known about diabetes?",
            date_from=date(2025, 1, 1),
            date_to=date(2024, 1, 1),
        )

    with pytest.raises(LiteratureQueryError, match="study type"):
        build_literature_query(
            "What is known about diabetes?",
            study_types=["randomized crossover"],
        )
