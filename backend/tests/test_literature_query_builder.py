"""Unit tests for the explainable and privacy-bounded query builder."""

from datetime import date

import pytest

from app.services.medical.literature.exceptions import LiteratureQueryError
from app.services.medical.literature.query_builder import (
    build_literature_query,
    redact_sensitive_text,
)


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


@pytest.mark.parametrize("question", [
    "What treatments exist for glaucoma?",
    "What is a regular software release?",
])
def test_short_gene_alias_does_not_match_an_english_substring(question: str) -> None:
    with pytest.raises(LiteratureQueryError, match="No medical concepts"):
        build_literature_query(question)


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
