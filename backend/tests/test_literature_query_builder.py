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
