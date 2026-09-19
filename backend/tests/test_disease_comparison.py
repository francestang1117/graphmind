"""Contract tests for the bounded disease-profile comparison preview."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.services.medical.disease_profile.comparison_builder import build_comparison_preview
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


def _input(document_id: str, *, coverage: dict | None = None, finding_count: int = 1) -> dict:
    document = _document(document_id)
    evidence = {
        "id": f"evidence-{document_id}",
        "evidence_id": f"evidence-{document_id}",
        "section_type": "results",
        "section_title": "Results",
        "page_start": 2,
        "page_end": 2,
        "quote": "The study reported this outcome.",
    }
    report = {
        "study_methods": {
            field: {
                "value": f"Reported {field}.",
                "support_status": "supported",
                "evidence_ids": [f"evidence-{document_id}"],
            }
            for field in (
                "design",
                "population",
                "human_animal_in_vitro",
                "sample_size",
                "comparator",
            )
        },
        "key_findings": [
            {
                "id": f"finding-{index}",
                "statement": f"Finding {index} from {document_id}.",
                "plain_explanation": "A report-level statement.",
                "evidence_ids": [f"evidence-{document_id}"],
            }
            for index in range(finding_count)
        ],
        "limitations": [],
    }
    if coverage is not None:
        report["coverage"] = coverage
    return {
        "document": document,
        "analyses": [{
            "run": {
                "run_id": f"run-{document_id}",
                "parsed_source_hash": f"parsed-{document_id}",
            },
            "report": report,
            "evidence": [evidence],
            "valid": True,
        }],
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


def test_builder_preserves_document_order_and_all_five_methods():
    preview = build_comparison_preview(
        concept_id="mesh:D000795",
        inputs=[
            _input("doc-2", coverage={"complete": True, "selected_chunks": 2, "total_chunks": 2}),
            _input("doc-1", coverage={"complete": False, "selected_chunks": 1, "total_chunks": 3}),
        ],
        language="en",
    )

    assert [document.document_id for document in preview.documents] == ["doc-2", "doc-1"]
    assert set(preview.documents[0].methods.model_dump()) == {
        "design",
        "population",
        "human_animal_in_vitro",
        "sample_size",
        "comparator",
    }
    assert preview.documents[0].coverage_status == "complete"
    assert preview.documents[1].coverage_status == "partial"
    assert any(question.document_id == "doc-2" for question in preview.discussion_questions)
    assert not any("contrad" in warning.lower() for warning in preview.warnings)


def test_builder_marks_missing_coverage_unknown_and_not_reported_without_evidence():
    record = _input("doc-1")
    record["analyses"][0]["report"]["study_methods"]["comparator"] = {
        "value": "A placebo group was used.",
        "support_status": "not_reported",
        "evidence_ids": ["evidence-doc-1"],
    }
    preview = build_comparison_preview(
        concept_id="mesh:D000795",
        inputs=[record, _input("doc-2")],
        language="zh",
    )

    document = preview.documents[0]
    assert document.coverage_status == "unknown"
    assert document.methods.comparator.value == "所选分析证据未报告此字段。"
    assert document.methods.comparator.evidence == []
    assert "comparison_coverage_unknown" in preview.warnings


def test_builder_filters_reference_evidence_and_marks_findings_truncated():
    record = _input("doc-1", finding_count=12)
    record["analyses"][0]["evidence"].append({
        "id": "reference-evidence",
        "evidence_id": "reference-evidence",
        "section_type": "references",
        "section_title": "References",
        "quote": "A citation list.",
    })
    record["analyses"][0]["report"]["key_findings"][0]["evidence_ids"] = [
        "reference-evidence"
    ]
    preview = build_comparison_preview(
        concept_id="mesh:D000795",
        inputs=[record, _input("doc-2")],
    )

    document = preview.documents[0]
    assert len(document.findings) == 10
    assert document.findings_total == 11
    assert document.findings_truncated is True
    assert len(preview.documents[1].findings) == 1


def test_builder_does_not_create_questions_without_source_evidence():
    record = _input("doc-1")
    for method in record["analyses"][0]["report"]["study_methods"].values():
        method["evidence_ids"] = []
    preview = build_comparison_preview(
        concept_id="mesh:D000795",
        inputs=[record, _input("doc-2")],
    )

    assert all(question.document_id != "doc-1" for question in preview.discussion_questions)


def test_builder_drops_evidence_from_another_document_or_analysis_run():
    record = _input("doc-1")
    record["analyses"][0]["evidence"][0].update({
        "document_id": "doc-2",
        "analysis_run_id": "run-doc-2",
    })

    preview = build_comparison_preview(
        concept_id="mesh:D000795",
        inputs=[record, _input("doc-2")],
    )

    document = preview.documents[0]
    assert all(method["evidence"] == [] for method in document.methods.model_dump().values())
    assert document.findings == []
    assert all(
        question.document_id != "doc-1"
        for question in preview.discussion_questions
    )


def test_builder_marks_long_evidence_quotes_as_truncated_prefixes():
    record = _input("doc-long-quote")
    long_quote = "A" * 6_000
    record["analyses"][0]["evidence"][0]["quote"] = long_quote

    preview = build_comparison_preview(
        concept_id="mesh:D000795",
        inputs=[record, _input("doc-2")],
    )

    evidence = preview.documents[0].methods.population.evidence[0]
    assert len(evidence.quote) == 5_000
    assert evidence.quote == long_quote[:5_000]
    assert evidence.quote_truncated is True
