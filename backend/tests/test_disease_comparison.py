"""Contract tests for the bounded disease-profile comparison preview."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.services.medical.disease_profile.models import (
    ComparisonDocument,
    ComparisonDocumentSelection,
    ComparisonEvidence,
    ComparisonPreview,
    ComparisonPreviewRequest,
)


def _selection(document_id: str) -> dict[str, str]:
    return {
        "document_id": document_id,
        "expected_parsed_source_hash": f"parsed-{document_id}",
    }


def _document(document_id: str) -> dict:
    evidence = {
        "document_id": document_id,
        "analysis_run_id": f"run-{document_id}",
        "evidence_id": f"evidence-{document_id}",
        "quote": "The study reported this outcome.",
        "section_type": "results",
        "section_title": "Results",
        "page_start": 2,
        "page_end": 2,
    }
    return {
        "document_id": document_id,
        "title": f"{document_id}.pdf",
        "document_kind": "research_paper",
        "document_date": "2026-01-01",
        "open_filename": f"{document_id}.pdf",
        "analysis_run_id": f"run-{document_id}",
        "parsed_source_hash": f"parsed-{document_id}",
        "coverage_status": "complete",
        "coverage": {
            "status": "complete",
            "selected_chunks": 3,
            "total_chunks": 3,
            "included_sections": ["methods", "results"],
            "omitted_sections": [],
        },
        "methods": {
            "design": {
                "value": "Randomized trial",
                "support_status": "supported",
                "evidence": [evidence],
                "warnings": [],
            },
        },
        "findings": [
            {
                "id": f"finding-{document_id}",
                "statement": "The study reported this outcome.",
                "explanation": "This is a report-level statement.",
                "evidence": [evidence],
                "warnings": [],
            }
        ],
        "findings_total": 1,
        "findings_truncated": False,
        "limitations": [],
        "limitations_total": 0,
        "limitations_truncated": False,
    }


def test_selection_requires_two_to_five_unique_documents():
    with pytest.raises(ValidationError):
        ComparisonPreviewRequest(documents=[_selection("doc-1")])
    with pytest.raises(ValidationError):
        ComparisonPreviewRequest(
            documents=[_selection("doc-1")] * 6,
        )
    with pytest.raises(ValidationError, match="unique"):
        ComparisonPreviewRequest(
            documents=[_selection("doc-1"), _selection("doc-1")],
        )

    request = ComparisonPreviewRequest(
        documents=[_selection("doc-1"), _selection("doc-2")],
        language="zh",
    )
    assert [item.document_id for item in request.documents] == ["doc-1", "doc-2"]


def test_contract_rejects_extra_fields_and_invalid_statuses():
    with pytest.raises(ValidationError):
        ComparisonDocumentSelection(
            **_selection("doc-1"),
            file_path="/private/path.pdf",
        )
    with pytest.raises(ValidationError):
        ComparisonEvidence(
            document_id="doc-1",
            analysis_run_id="run-1",
            evidence_id="evidence-1",
            quote="A quote.",
            support_status="supported",
        )
    with pytest.raises(ValidationError):
        ComparisonPreviewRequest(
            documents=[_selection("doc-1"), _selection("doc-2")],
            language="fr",
        )


def test_preview_contract_has_fixed_methods_and_bounded_lists():
    document = ComparisonDocument.model_validate(_document("doc-1"))
    assert set(document.methods.model_dump()) == {
        "design",
        "population",
        "human_animal_in_vitro",
        "sample_size",
        "comparator",
    }
    assert document.methods.population.support_status == "not_reported"
    assert document.methods.population.evidence == []

    preview = ComparisonPreview(
        concept_id="mesh:D000795",
        documents=[document, ComparisonDocument.model_validate(_document("doc-2"))],
        discussion_questions=[],
        warnings=[],
    )
    assert [item.document_id for item in preview.documents] == ["doc-1", "doc-2"]


def test_not_reported_method_can_be_explicit_without_fabricated_evidence():
    payload = _document("doc-1")
    payload["methods"] = {
        field: {
            "value": "The selected analysis evidence did not report this field.",
            "support_status": "not_reported",
            "evidence": [],
            "warnings": [],
        }
        for field in (
            "design",
            "population",
            "human_animal_in_vitro",
            "sample_size",
            "comparator",
        )
    }
    document = ComparisonDocument.model_validate(payload)
    assert document.methods.comparator.support_status == "not_reported"
    assert document.methods.comparator.evidence == []


def test_findings_and_questions_are_bounded_by_the_contract():
    payload = _document("doc-1")
    payload["findings"] = [
        {
            "id": f"finding-{index}",
            "statement": "A supported finding.",
            "evidence": [],
        }
        for index in range(11)
    ]
    with pytest.raises(ValidationError):
        ComparisonDocument.model_validate(payload)

    documents = [ComparisonDocument.model_validate(_document("doc-1")), ComparisonDocument.model_validate(_document("doc-2"))]
    with pytest.raises(ValidationError):
        ComparisonPreview(
            concept_id="mesh:D000795",
            documents=documents,
            discussion_questions=[
                {
                    "id": f"q-{index}",
                    "question": "What should be clarified with a clinician?",
                    "document_id": "doc-1",
                }
                for index in range(4)
            ],
        )
