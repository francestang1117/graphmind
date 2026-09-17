"""Regression tests for the deterministic disease profile read model."""

from __future__ import annotations

import uuid

import pytest

from app.core.database import SessionLocal
from app.models.persistence import DocumentDiseaseLinkRecord, DocumentRecord
from app.services.medical.disease_profile.aggregator import DiseaseProfileAggregator
from app.services.medical.disease_profile.exceptions import DiseaseProfileError
from app.services.medical.disease_profile.repository import DiseaseProfileRepository


def _evidence(evidence_id: str, *, section_type: str = "results") -> dict:
    return {
        "id": f"row-{evidence_id}",
        "evidence_id": evidence_id,
        "finding_id": "finding-1",
        "chunk_id": f"chunk-{evidence_id}",
        "section_type": section_type,
        "section_title": section_type.title(),
        "page_start": 2,
        "page_end": 2,
        "quote": "The source reports a measured outcome.",
    }


def _record(
    document_id: str,
    *,
    title: str,
    alias: str,
    run_id: str,
    article_id: str = "PMID-1",
    article_status: str = "normal",
    valid: bool = True,
    user_note: str = "private note should not leave Visit Prep",
) -> dict:
    report = {
        "key_findings": [{
            "id": f"finding-{run_id}",
            "statement": f"Finding from {title}",
            "plain_explanation": "The result is shown without combining it with another paper.",
            "evidence_ids": ["EVIDENCE-1"],
            "interpretation_type": "direct_statement",
        }],
        "study_methods": {
            "population": {
                "value": "Adults with the condition",
                "support_status": "supported",
                "evidence_ids": ["EVIDENCE-1"],
            },
            "human_animal_in_vitro": {
                "value": "human participants",
                "support_status": "supported",
                "evidence_ids": ["EVIDENCE-1"],
            },
            "sample_size": {
                "value": "40 participants",
                "support_status": "supported",
                "evidence_ids": ["EVIDENCE-1"],
            },
            "comparator": {
                "value": "usual care",
                "support_status": "supported",
                "evidence_ids": ["EVIDENCE-1"],
            },
        },
        "limitations": [],
        "medical_terms": [],
    }
    return {
        "link": {
            "concept_id": "mesh:D000795",
            "preferred_name_en": "Fabry Disease",
            "preferred_name_zh": "法布雷病",
            "matched_alias": alias,
            "ontology_version": "test-v1",
            "updated_at": "2026-09-18T00:00:00+00:00",
        },
        "document": {
            "document_id": document_id,
            "title": title,
            "document_kind": "research_paper",
            "language": "en",
            "document_date": "2026-01-01",
            "file_hash": f"file-{document_id}",
            "parsed_source_hash": f"parsed-{document_id}",
            "modified_at": "2026-09-18T00:00:00+00:00",
        },
        "analyses": [{
            "run": {
                "run_id": run_id,
                "document_id": document_id,
                "status": "succeeded",
                "source_hash": f"file-{document_id}",
                "parsed_source_hash": f"parsed-{document_id}",
                "validation_status": "validated",
                "is_current": True,
                "updated_at": "2026-09-18T00:00:00+00:00",
            },
            "report": report,
            "evidence": [_evidence("EVIDENCE-1")],
            "valid": valid,
            "warnings": [] if valid else ["analysis_report_unavailable"],
        }],
        "matches": [{
            "analysis_run_id": run_id,
            "match_specificity": "finding_specific",
            "relevance_score": 82,
            "article": {
                "source": "pubmed",
                "external_id": article_id,
                "title": "A related public study",
                "journal": "Example Journal",
                "publication_types": ["Clinical Trial"],
                "source_url": f"https://pubmed.ncbi.nlm.nih.gov/{article_id}",
                "retraction_status": article_status,
            },
        }],
        "questions": [{
            "id": f"question-{run_id}",
            "analysis_run_id": run_id,
            "question": "Which participants were included?",
            "rationale": "The study population is important to discuss.",
            "category": "applicability",
            "topic": "study_population",
            "source_kind": "study_methods",
            "source_id": "population",
            "evidence_ids": ["EVIDENCE-1"],
            "user_note": user_note,
        }],
    }


def test_aggregator_keeps_multiple_documents_and_deduplicates_external_articles():
    aggregator = DiseaseProfileAggregator()
    payload = aggregator.aggregate(
        concept_id="mesh:D000795",
        inputs=[
            _record("doc-a", title="English paper", alias="Fabry Disease", run_id="run-a"),
            _record(
                "doc-b",
                title="中文论文",
                alias="法布雷病",
                run_id="run-b",
                article_status="retracted",
            ),
        ],
    )

    assert payload["document_count"] == 2
    assert len(payload["documents"]) == 2
    assert payload["section_counts"]["key_findings"] == 2
    assert payload["external_article_count"] == 0
    assert payload["stats"]["flagged_article_count"] == 1
    assert payload["warnings"] == ["retracted_external_article_present"]
    assert len(payload["sections"]["external_studies"]) == 1
    assert all("private note" not in str(item) for item in payload["sections"]["clinician_questions"])
    assert payload["saved_question_count"] == 2


def test_aggregator_excludes_stale_analysis_and_never_keeps_not_reported_value():
    record = _record("doc-stale", title="Stale paper", alias="Fabry Disease", run_id="run-stale", valid=False)
    record["analyses"][0]["report"]["study_methods"]["sample_size"] = {
        "value": "900 patients",
        "support_status": "not_reported",
        "evidence_ids": ["EVIDENCE-1"],
    }
    payload = DiseaseProfileAggregator().aggregate(
        concept_id="mesh:D000795",
        inputs=[record],
    )

    assert payload["analysis_count"] == 0
    assert payload["sections"]["key_findings"] == []
    assert payload["stats"]["expired_analysis_count"] == 1


def test_aggregator_sanitizes_not_reported_attributes_from_current_input():
    record = _record("doc-current", title="Current paper", alias="Fabry Disease", run_id="run-current")
    record["analyses"][0]["report"]["study_methods"]["sample_size"] = {
        "value": "900 patients",
        "support_status": "not_reported",
        "evidence_ids": ["EVIDENCE-1"],
    }
    payload = DiseaseProfileAggregator().aggregate(
        concept_id="mesh:D000795",
        inputs=[record],
    )
    item = next(
        value
        for value in payload["sections"]["study_methods"]
        if value["title"] == "Sample Size"
    )

    assert item["value"] == "Not reported in the source analysis."
    assert item["evidence_ids"] == []
    assert item["evidence"] == []


def test_repository_links_are_idempotent_and_scope_checked():
    suffix = uuid.uuid4().hex
    document_id = f"document-{suffix}"
    user_id = f"user-{suffix}"
    workspace_id = f"workspace-{suffix}"
    with SessionLocal() as db:
        db.add(DocumentRecord(
            id=document_id,
            user_id=user_id,
            workspace_id=workspace_id,
            filename="paper.pdf",
            stored_filename="stored.pdf",
            original_filename="paper.pdf",
            file_extension="pdf",
            file_type="pdf",
            mime_type="application/pdf",
            file_hash=f"hash-{suffix}",
            file_path="/tmp/paper.pdf",
            file_size=10,
            status="completed",
            document_kind="research_paper",
            language="en",
            parsed_source_hash=f"parsed-{suffix}",
        ))
        db.commit()

    repository = DiseaseProfileRepository()
    kwargs = {
        "user_id": user_id,
        "workspace_id": workspace_id,
        "document_id": document_id,
        "concept_id": "mesh:D000795",
        "preferred_name_en": "Fabry Disease",
        "preferred_name_zh": "法布雷病",
        "matched_alias": "法布雷病",
        "ontology_version": "test-v1",
    }
    first, created = repository.create_link(**kwargs)
    second, created_again = repository.create_link(**kwargs)
    assert created is True
    assert created_again is False
    assert first["id"] == second["id"]

    with pytest.raises(DiseaseProfileError) as error:
        repository.create_link(
            **{
                **kwargs,
                "concept_id": "mesh:D005776",
                "preferred_name_en": "Gaucher Disease",
                "preferred_name_zh": "戈谢病",
                "matched_alias": "戈谢病",
            }
        )
    assert error.value.code == "disease_link_primary_exists"
    assert error.value.status_code == 409

    with pytest.raises(DiseaseProfileError) as error:
        repository.create_link(**{**kwargs, "workspace_id": f"other-{suffix}"})
    assert error.value.code == "disease_link_document_not_found"

    with SessionLocal() as db:
        links = db.query(DocumentDiseaseLinkRecord).filter_by(document_id=document_id).all()
        assert len(links) == 1
        assert links[0].concept_id == "mesh:D000795"

    assert repository.delete_for_document(
        document_id,
        user_id=user_id,
        workspace_id=workspace_id,
    ) is None
    with SessionLocal() as db:
        assert db.query(DocumentDiseaseLinkRecord).filter_by(document_id=document_id).count() == 0
        db.query(DocumentRecord).filter_by(id=document_id).delete()
        db.commit()
