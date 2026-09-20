"""Regression tests for the deterministic disease profile read model."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import uuid

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.pool import NullPool
from sqlalchemy.orm import sessionmaker

from app.core.database import Base, SessionLocal
from app.models.persistence import (
    DocumentDiseaseLinkRecord,
    DocumentRecord,
    MedicalAnalysisEvidenceRecord,
    MedicalAnalysisResultRecord,
    MedicalAnalysisRunRecord,
)
from app.services.medical.disease_profile.aggregator import DiseaseProfileAggregator
from app.services.medical.disease_profile.exceptions import DiseaseProfileError
from app.services.medical.disease_profile.repository import (
    DiseaseProfileRepository,
    ProfileInputOptions,
)
from app.services.medical.disease_profile.service import DiseaseProfileService


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


def _comparison_report_json(
    evidence_id: str,
    *,
    schema_version: str = "medical-insights-v3",
    include_coverage: bool = True,
) -> str:
    payload = {
        "schema_version": schema_version,
        "document_kind": "research_paper",
        "language": "en",
        "overview": {
            "title": "Comparison source",
            "summary": "A saved report used by the comparison read path.",
            "evidence_ids": [evidence_id],
        },
        "study_methods": {
            "population": {
                "value": "Adults",
                "support_status": "supported",
                "evidence_ids": [evidence_id],
            },
        },
        "key_findings": [{
            "id": "finding-1",
            "statement": "The source reported an outcome.",
            "plain_explanation": "The comparison keeps this statement attached to its source.",
            "evidence_ids": [evidence_id],
        }],
        "limitations": [],
    }
    if include_coverage:
        payload["coverage"] = {
            "complete": True,
            "selected_chunks": 2,
            "total_chunks": 2,
            "included_sections": ["methods", "results"],
            "omitted_sections": [],
        }
    return json.dumps(payload, ensure_ascii=False)


def _seed_comparison_snapshot(
    sessions,
    *,
    suffix: str,
    user_id: str,
    workspace_id: str,
    document_id: str,
    run_id: str,
    parsed_source_hash: str = "parsed-snapshot",
    evidence_id: str = "EVIDENCE-before",
    file_hash: str = "file-snapshot",
) -> None:
    with sessions() as db:
        db.add(
            DocumentRecord(
                id=document_id,
                user_id=user_id,
                workspace_id=workspace_id,
                filename=f"{document_id}.pdf",
                stored_filename=f"stored-{document_id}.pdf",
                original_filename="snapshot-paper.pdf",
                file_extension="pdf",
                file_type="pdf",
                mime_type="application/pdf",
                file_hash=file_hash,
                file_path=f"/tmp/{document_id}.pdf",
                file_size=10,
                status="completed",
                document_kind="research_paper",
                language="en",
                parsed_source_hash=parsed_source_hash,
            )
        )
        db.flush()
        db.add(
            DocumentDiseaseLinkRecord(
                id=f"comparison-snapshot-link-{suffix}",
                user_id=user_id,
                workspace_id=workspace_id,
                document_id=document_id,
                concept_id="mesh:D000795",
                preferred_name_en="Fabry Disease",
                preferred_name_zh="Fabry Disease",
                matched_alias="Fabry Disease",
                ontology_version="test-v1",
                link_source="manual_selection",
            )
        )
        db.add(
            MedicalAnalysisRunRecord(
                id=run_id,
                user_id=user_id,
                workspace_id=workspace_id,
                document_id=document_id,
                requested_by=user_id,
                status="succeeded",
                source_hash=file_hash,
                parsed_source_hash=parsed_source_hash,
                analysis_key=f"comparison-snapshot-{run_id}",
                is_current=True,
            )
        )
        db.flush()
        db.add(
            MedicalAnalysisResultRecord(
                run_id=run_id,
                report_json=_comparison_report_json(evidence_id),
                validation_status="validated",
            )
        )
        db.add(
            MedicalAnalysisEvidenceRecord(
                id=f"comparison-snapshot-evidence-{suffix}",
                evidence_id=evidence_id,
                run_id=run_id,
                finding_id=f"finding-{run_id}",
                chunk_id=f"chunk-{run_id}",
                section_type="results",
                section_title="Results",
                quoted_text=f"Evidence from {run_id}.",
                page_start=2,
                page_end=2,
            )
        )
        db.commit()


def _replace_comparison_snapshot(
    sessions,
    *,
    document_id: str,
    old_run_id: str,
    new_run_id: str,
    change_document: bool,
) -> None:
    with sessions() as db:
        old_run = db.get(MedicalAnalysisRunRecord, old_run_id)
        assert old_run is not None
        old_run.is_current = False
        parsed_source_hash = "parsed-snapshot-v2" if change_document else "parsed-snapshot"
        if change_document:
            document = db.get(DocumentRecord, document_id)
            assert document is not None
            document.parsed_source_hash = parsed_source_hash
        db.add(
            MedicalAnalysisRunRecord(
                id=new_run_id,
                user_id=old_run.user_id,
                workspace_id=old_run.workspace_id,
                document_id=document_id,
                requested_by=old_run.user_id,
                status="succeeded",
                source_hash="file-snapshot",
                parsed_source_hash=parsed_source_hash,
                analysis_key=f"comparison-snapshot-{new_run_id}",
                is_current=True,
            )
        )
        db.flush()
        db.add(
            MedicalAnalysisResultRecord(
                run_id=new_run_id,
                report_json=_comparison_report_json("EVIDENCE-after"),
                validation_status="validated",
            )
        )
        db.add(
            MedicalAnalysisEvidenceRecord(
                id=f"comparison-snapshot-evidence-{new_run_id}",
                evidence_id="EVIDENCE-after",
                run_id=new_run_id,
                finding_id=f"finding-{new_run_id}",
                chunk_id=f"chunk-{new_run_id}",
                section_type="results",
                section_title="Results",
                quoted_text="Evidence from the replacement analysis.",
                page_start=3,
                page_end=3,
            )
        )
        db.commit()


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


def test_aggregator_merges_identical_clinician_questions_and_keeps_sources():
    payload = DiseaseProfileAggregator().aggregate(
        concept_id="mesh:D000795",
        inputs=[
            _record("doc-a", title="English paper", alias="Fabry Disease", run_id="run-a"),
            _record("doc-b", title="Second paper", alias="Fabry Disease", run_id="run-b"),
        ],
    )

    questions = payload["sections"]["clinician_questions"]
    assert len(questions) == 1
    assert payload["section_counts"]["clinician_questions"] == 1
    assert questions[0]["document_ids"] == ["doc-a", "doc-b"]
    assert questions[0]["related_document_count"] == 2
    assert len(questions[0]["evidence"]) == 2


def test_aggregator_bounds_external_article_document_preview_and_counts_all_sources():
    records = [
        _record(
            f"external-doc-{index}",
            title=f"External source {index}",
            alias="Fabry Disease",
            run_id=f"external-run-{index}",
            article_id="PMID-SHARED",
        )
        for index in range(101)
    ]

    payload = DiseaseProfileAggregator().aggregate(
        concept_id="mesh:D000795",
        inputs=records,
    )
    article = payload["sections"]["external_studies"][0]

    assert article["related_document_count"] == 101
    assert len(article["document_ids"]) == 20
    assert len(article["document_titles"]) == 20
    assert article["related_documents_truncated"] is True


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


def test_aggregator_summary_keeps_counts_without_retaining_items():
    record = _record("doc-summary", title="Summary paper", alias="Fabry Disease", run_id="run-summary")

    summary = DiseaseProfileAggregator().aggregate_summary(
        concept_id="mesh:D000795",
        inputs=[record],
    )

    assert summary["section_counts"]["key_findings"] == 1
    assert summary["section_counts"]["study_methods"] == 4
    assert summary["section_counts"]["clinician_questions"] == 1
    assert summary["sections"]["key_findings"] == []
    assert summary["_all_sections"] == {}


def test_aggregator_section_does_not_build_unrequested_sections():
    record = _record("doc-section", title="Section paper", alias="Fabry Disease", run_id="run-section")

    payload = DiseaseProfileAggregator().aggregate_section(
        concept_id="mesh:D000795",
        inputs=[record],
        section="external_studies",
    )

    assert len(payload["_all_sections"]["external_studies"]) == 1
    assert payload["_all_sections"]["key_findings"] == []
    assert payload["_all_sections"]["clinician_questions"] == []
    assert payload["section_counts"]["key_findings"] == 0


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


def test_invalid_current_report_is_not_advertised_as_comparable_profile_source():
    suffix = uuid.uuid4().hex
    user_id = f"invalid-report-user-{suffix}"
    workspace_id = f"invalid-report-workspace-{suffix}"
    valid_document_id = f"invalid-report-valid-document-{suffix}"
    invalid_document_id = f"invalid-report-invalid-document-{suffix}"
    valid_run_id = f"invalid-report-valid-run-{suffix}"
    invalid_run_id = f"invalid-report-invalid-run-{suffix}"

    try:
        _seed_comparison_snapshot(
            SessionLocal,
            suffix=f"{suffix}-valid",
            user_id=user_id,
            workspace_id=workspace_id,
            document_id=valid_document_id,
            run_id=valid_run_id,
        )
        _seed_comparison_snapshot(
            SessionLocal,
            suffix=f"{suffix}-invalid",
            user_id=user_id,
            workspace_id=workspace_id,
            document_id=invalid_document_id,
            run_id=invalid_run_id,
            file_hash=f"file-{invalid_document_id}",
        )
        with SessionLocal() as db:
            invalid_result = db.get(MedicalAnalysisResultRecord, invalid_run_id)
            assert invalid_result is not None
            invalid_result.report_json = "{}"
            db.commit()

        repository = DiseaseProfileRepository()
        document_page = repository.list_profile_documents(
            user_id=user_id,
            workspace_id=workspace_id,
            concept_id="mesh:D000795",
            limit=20,
        )
        documents_by_id = {item["document_id"]: item for item in document_page["items"]}
        assert documents_by_id[valid_document_id]["source_status"] == "current"
        assert documents_by_id[valid_document_id]["current_analysis_run_id"] == valid_run_id
        assert documents_by_id[invalid_document_id]["source_status"] == "outdated"
        assert documents_by_id[invalid_document_id]["current_analysis_run_id"] is None
        assert "analysis_report_unavailable" in documents_by_id[invalid_document_id]["warnings"]

        grouped = repository.load_profile_inputs(
            user_id=user_id,
            workspace_id=workspace_id,
            concept_ids=["mesh:D000795"],
            include=ProfileInputOptions(analyses=True, evidence=False, literature_matches=False, clinician_questions=False),
        )
        records_by_id = {
            record["document"]["document_id"]: record
            for record in grouped["mesh:D000795"]
        }
        assert records_by_id[valid_document_id]["analyses"][0]["valid"] is True
        assert records_by_id[invalid_document_id]["analyses"][0]["valid"] is False
        assert records_by_id[invalid_document_id]["analyses"][0]["report"] is None

        profile = DiseaseProfileService(repository=repository).get_profile(
            user_id=user_id,
            workspace_id=workspace_id,
            concept_id="mesh:D000795",
        )
        assert profile is not None
        assert profile["stats"]["valid_analysis_count"] == 1
    finally:
        with SessionLocal() as db:
            db.query(MedicalAnalysisEvidenceRecord).filter(
                MedicalAnalysisEvidenceRecord.run_id.in_([valid_run_id, invalid_run_id])
            ).delete(synchronize_session=False)
            db.query(MedicalAnalysisResultRecord).filter(
                MedicalAnalysisResultRecord.run_id.in_([valid_run_id, invalid_run_id])
            ).delete(synchronize_session=False)
            db.query(MedicalAnalysisRunRecord).filter(
                MedicalAnalysisRunRecord.id.in_([valid_run_id, invalid_run_id])
            ).delete(synchronize_session=False)
            db.query(DocumentDiseaseLinkRecord).filter_by(
                user_id=user_id,
                workspace_id=workspace_id,
            ).delete(synchronize_session=False)
            db.query(DocumentRecord).filter_by(
                user_id=user_id,
                workspace_id=workspace_id,
            ).delete(synchronize_session=False)
            db.commit()


def test_repository_loads_only_selected_scoped_comparison_inputs():
    suffix = uuid.uuid4().hex
    user_id = f"comparison-user-{suffix}"
    workspace_id = f"comparison-workspace-{suffix}"
    concept_id = "mesh:D000795"
    document_ids = [f"comparison-document-{suffix}-{index}" for index in range(3)]
    run_ids = [f"comparison-run-{suffix}-{index}" for index in range(3)]
    history_run_ids: list[str] = []

    try:
        with SessionLocal() as db:
            for index, (document_id, run_id) in enumerate(zip(document_ids, run_ids)):
                db.add(
                    DocumentRecord(
                        id=document_id,
                        user_id=user_id,
                        workspace_id=workspace_id,
                        filename=f"stored-{document_id}.pdf",
                        stored_filename=f"stored-{document_id}.pdf",
                        original_filename=f"paper-{index}.pdf",
                        file_extension="pdf",
                        file_type="pdf",
                        mime_type="application/pdf",
                        file_hash=f"file-{document_id}",
                        file_path=f"/tmp/{document_id}.pdf",
                        file_size=10,
                        status="completed",
                        document_kind="research_paper",
                        language="en",
                        parsed_source_hash=f"parsed-{document_id}",
                    )
                )
                db.flush()
                db.add(
                    DocumentDiseaseLinkRecord(
                        id=f"comparison-link-{suffix}-{index}",
                        user_id=user_id,
                        workspace_id=workspace_id,
                        document_id=document_id,
                        concept_id=concept_id,
                        preferred_name_en="Fabry Disease",
                        preferred_name_zh="法布雷病",
                        matched_alias="Fabry Disease",
                        ontology_version="test-v1",
                        link_source="manual_selection",
                    )
                )
                db.add(
                        MedicalAnalysisRunRecord(
                        id=run_id,
                        user_id=user_id,
                        workspace_id=workspace_id,
                        document_id=document_id,
                        requested_by=user_id,
                        status="succeeded",
                        source_hash=f"file-{document_id}",
                        parsed_source_hash=f"parsed-{document_id}",
                        analysis_key=f"comparison-key-{document_id}",
                        is_current=True,
                    )
                )
                db.flush()
                db.add(
                    MedicalAnalysisResultRecord(
                        run_id=run_id,
                        report_json=_comparison_report_json(f"EVIDENCE-{index}"),
                        validation_status="validated",
                    )
                )
                db.flush()
                db.add(
                    MedicalAnalysisEvidenceRecord(
                        id=f"comparison-evidence-{suffix}-{index}",
                        evidence_id=f"EVIDENCE-{index}",
                        run_id=run_id,
                        finding_id=f"finding-{index}",
                        chunk_id=f"chunk-{index}",
                        section_type="results",
                        section_title="Results",
                        quoted_text=f"Evidence from {document_id}.",
                        page_start=2,
                        page_end=2,
                    )
                )
                if index == 0:
                    for history_index in range(100):
                        history_run_id = f"comparison-history-{suffix}-{history_index}"
                        history_run_ids.append(history_run_id)
                        db.add(
                            MedicalAnalysisRunRecord(
                                id=history_run_id,
                                user_id=user_id,
                                workspace_id=workspace_id,
                                document_id=document_id,
                                requested_by=user_id,
                                status="succeeded",
                                source_hash=f"file-{document_id}",
                                parsed_source_hash=f"parsed-{document_id}",
                                analysis_key=f"comparison-history-key-{history_index}",
                                is_current=False,
                            )
                        )
                        db.flush()
                        db.add(
                            MedicalAnalysisResultRecord(
                                run_id=history_run_id,
                                report_json="{}",
                                validation_status="validated",
                            )
                        )
            db.commit()

        records = DiseaseProfileRepository().load_comparison_inputs(
            user_id=user_id,
            workspace_id=workspace_id,
            concept_id=concept_id,
            document_ids=[document_ids[2], document_ids[0]],
        )

        assert [record["document"]["document_id"] for record in records] == [
            document_ids[2],
            document_ids[0],
        ]
        assert all(len(record["analyses"]) == 1 for record in records)
        assert all(record["analyses"][0]["valid"] for record in records)
        assert [record["document"]["current_analysis_run_id"] for record in records] == [
            run_ids[2],
            run_ids[0],
        ]
        assert [record["analyses"][0]["evidence"][0]["evidence_id"] for record in records] == [
            "EVIDENCE-2",
            "EVIDENCE-0",
        ]
        assert all("open_filename" in record["document"] for record in records)

        preview = DiseaseProfileService(
            repository=DiseaseProfileRepository(),
        ).preview_comparison(
            user_id=user_id,
            workspace_id=workspace_id,
            concept_id=concept_id,
            documents=[
                {
                    "document_id": document_ids[2],
                    "expected_parsed_source_hash": f"parsed-{document_ids[2]}",
                    "expected_analysis_run_id": run_ids[2],
                },
                {
                    "document_id": document_ids[0],
                    "expected_parsed_source_hash": f"parsed-{document_ids[0]}",
                    "expected_analysis_run_id": run_ids[0],
                },
            ],
            language="en",
        )
        assert [document["document_id"] for document in preview["documents"]] == [
            document_ids[2],
            document_ids[0],
        ]
        assert all(document["open_filename"] for document in preview["documents"])

        with SessionLocal() as db:
            run = db.get(MedicalAnalysisRunRecord, run_ids[0])
            result = db.get(MedicalAnalysisResultRecord, run_ids[0])
            assert run is not None
            assert result is not None
            run.schema_version = "medical-insights-v2"
            result.report_json = _comparison_report_json(
                "EVIDENCE-0",
                schema_version="medical-insights-v2",
            )
            db.commit()
        legacy_report = DiseaseProfileRepository().load_comparison_inputs(
            user_id=user_id,
            workspace_id=workspace_id,
            concept_id=concept_id,
            document_ids=[document_ids[0]],
        )
        assert legacy_report[0]["analyses"][0]["report"]["schema_version"] == "medical-insights-v2"

        with SessionLocal() as db:
            result = db.get(MedicalAnalysisResultRecord, run_ids[0])
            assert result is not None
            result.report_json = _comparison_report_json(
                "EVIDENCE-0",
                schema_version="medical-insights-v2",
                include_coverage=False,
            )
            db.commit()
        missing_coverage = DiseaseProfileRepository().load_comparison_inputs(
            user_id=user_id,
            workspace_id=workspace_id,
            concept_id=concept_id,
            document_ids=[document_ids[0]],
        )
        assert "coverage" not in missing_coverage[0]["analyses"][0]["report"]

        with SessionLocal() as db:
            result = db.get(MedicalAnalysisResultRecord, run_ids[0])
            assert result is not None
            result.report_json = "{}"
            db.commit()
        with pytest.raises(DiseaseProfileError) as error:
            DiseaseProfileRepository().load_comparison_inputs(
                user_id=user_id,
                workspace_id=workspace_id,
                concept_id=concept_id,
                document_ids=[document_ids[0]],
            )
        assert error.value.code == "comparison_report_invalid"
    finally:
        with SessionLocal() as db:
            db.query(MedicalAnalysisEvidenceRecord).filter(
                MedicalAnalysisEvidenceRecord.run_id.in_(run_ids + history_run_ids)
            ).delete(synchronize_session=False)
            db.query(MedicalAnalysisResultRecord).filter(
                MedicalAnalysisResultRecord.run_id.in_(run_ids + history_run_ids)
            ).delete(synchronize_session=False)
            db.query(MedicalAnalysisRunRecord).filter(
                MedicalAnalysisRunRecord.id.in_(run_ids + history_run_ids)
            ).delete(synchronize_session=False)
            db.query(DocumentDiseaseLinkRecord).filter_by(
                user_id=user_id,
                workspace_id=workspace_id,
            ).delete(synchronize_session=False)
            db.query(DocumentRecord).filter_by(
                user_id=user_id,
                workspace_id=workspace_id,
            ).delete(synchronize_session=False)
            db.commit()


@pytest.mark.parametrize("change_document", [False, True])
def test_sqlite_comparison_read_keeps_one_snapshot(change_document: bool):
    """SQLite comparison reads must not combine document and analysis versions."""
    with tempfile.TemporaryDirectory(prefix="graphmind-comparison-sqlite-") as directory:
        database_path = os.path.join(directory, "comparison.sqlite3")
        engine = create_engine(
            f"sqlite:///{database_path}",
            future=True,
            poolclass=NullPool,
            connect_args={"check_same_thread": False, "timeout": 10},
        )

        def configure_sqlite(dbapi_connection, _connection_record):
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA busy_timeout=10000")
            finally:
                cursor.close()

        event.listen(engine, "connect", configure_sqlite)
        sessions = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
        Base.metadata.create_all(engine)
        suffix = uuid.uuid4().hex[:12]
        user_id = f"sqlite-snapshot-user-{suffix}"
        workspace_id = f"sqlite-snapshot-workspace-{suffix}"
        document_id = f"sqlite-snapshot-document-{suffix}"
        run_before = f"sqlite-snapshot-run-before-{suffix}"
        run_after = f"sqlite-snapshot-run-after-{suffix}"
        _seed_comparison_snapshot(
            sessions,
            suffix=suffix,
            user_id=user_id,
            workspace_id=workspace_id,
            document_id=document_id,
            run_id=run_before,
        )

        first_select_finished = threading.Event()
        allow_reader = threading.Event()
        reader_state = threading.local()
        listener_state = {"paused": False}

        def pause_after_link_read(_conn, _cursor, statement, _parameters, _context, _executemany):
            if (
                getattr(reader_state, "name", "") == "reader"
                and not listener_state["paused"]
                and "document_disease_links" in statement.lower()
            ):
                listener_state["paused"] = True
                first_select_finished.set()
                assert allow_reader.wait(10), "reader was not released after the concurrent update"

        event.listen(engine, "after_cursor_execute", pause_after_link_read)
        repository = DiseaseProfileRepository(sessions, enabled=lambda: True)
        outcome: dict[str, object] = {}

        def read_comparison():
            reader_state.name = "reader"
            try:
                outcome["records"] = repository.load_comparison_inputs(
                    user_id=user_id,
                    workspace_id=workspace_id,
                    concept_id="mesh:D000795",
                    document_ids=[document_id],
                )
            except BaseException as exc:
                outcome["error"] = exc

        reader = threading.Thread(target=read_comparison)
        reader.start()
        assert first_select_finished.wait(10), "comparison reader did not reach its first SELECT"
        _replace_comparison_snapshot(
            sessions,
            document_id=document_id,
            old_run_id=run_before,
            new_run_id=run_after,
            change_document=change_document,
        )
        allow_reader.set()
        reader.join(timeout=20)
        assert not reader.is_alive(), "comparison reader did not finish"

        try:
            if "error" in outcome:
                assert change_document
                assert getattr(outcome["error"], "code", "") == "comparison_source_changed"
            else:
                records = outcome["records"]
                assert records[0]["document"]["parsed_source_hash"] == "parsed-snapshot"
                assert records[0]["analyses"][0]["run"]["run_id"] == run_before
                assert records[0]["analyses"][0]["evidence"][0]["evidence_id"] == "EVIDENCE-before"
        finally:
            event.remove(engine, "after_cursor_execute", pause_after_link_read)
            engine.dispose()


def test_sqlite_comparison_read_rolls_back_after_mid_read_error():
    """A failed snapshot read must not poison the next independent read."""
    with tempfile.TemporaryDirectory(prefix="graphmind-comparison-sqlite-rollback-") as directory:
        database_path = os.path.join(directory, "comparison.sqlite3")
        engine = create_engine(
            f"sqlite:///{database_path}",
            future=True,
            poolclass=NullPool,
            connect_args={"check_same_thread": False, "timeout": 10},
        )
        sessions = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
        Base.metadata.create_all(engine)
        suffix = uuid.uuid4().hex[:12]
        document_id = f"sqlite-rollback-document-{suffix}"
        run_id = f"sqlite-rollback-run-{suffix}"
        _seed_comparison_snapshot(
            sessions,
            suffix=suffix,
            user_id=f"sqlite-rollback-user-{suffix}",
            workspace_id=f"sqlite-rollback-workspace-{suffix}",
            document_id=document_id,
            run_id=run_id,
        )
        repository = DiseaseProfileRepository(sessions, enabled=lambda: True)
        original_load_evidence = repository._load_evidence

        def fail_mid_read(_db, _run_ids):
            raise RuntimeError("simulated comparison read failure")

        repository._load_evidence = fail_mid_read  # type: ignore[method-assign]
        with pytest.raises(RuntimeError, match="simulated comparison read failure"):
            repository.load_comparison_inputs(
                user_id=f"sqlite-rollback-user-{suffix}",
                workspace_id=f"sqlite-rollback-workspace-{suffix}",
                concept_id="mesh:D000795",
                document_ids=[document_id],
            )

        repository._load_evidence = original_load_evidence  # type: ignore[method-assign]
        records = repository.load_comparison_inputs(
            user_id=f"sqlite-rollback-user-{suffix}",
            workspace_id=f"sqlite-rollback-workspace-{suffix}",
            concept_id="mesh:D000795",
            document_ids=[document_id],
        )
        assert records[0]["analyses"][0]["run"]["run_id"] == run_id
        engine.dispose()


@pytest.mark.parametrize("change_document", [False, True])
def test_postgres_comparison_read_keeps_one_repeatable_snapshot(change_document: bool):
    """A current-analysis update between repository SELECTs cannot mix versions."""
    url = (
        os.getenv("GRAPHMIND_TEST_POSTGRES_URL")
        or os.getenv("TEST_POSTGRES_URL")
        or os.getenv("POSTGRES_TEST_DATABASE_URL")
    )
    if not url or not url.startswith("postgresql"):
        pytest.skip("set GRAPHMIND_TEST_POSTGRES_URL to test comparison snapshots")

    suffix = uuid.uuid4().hex[:12]
    schema = f"comparison_snapshot_{suffix}"
    user_id = f"comparison-snapshot-user-{suffix}"
    workspace_id = f"comparison-snapshot-workspace-{suffix}"
    document_id = f"comparison-snapshot-document-{suffix}"
    run_before = f"comparison-snapshot-run-before-{suffix}"
    run_after = f"comparison-snapshot-run-after-{suffix}"
    admin = create_engine(url, future=True)
    with admin.begin() as db:
        db.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    engine = create_engine(
        url,
        future=True,
        poolclass=NullPool,
        connect_args={
            "options": f"-csearch_path={schema} -clock_timeout=5000 -cstatement_timeout=10000"
        },
    )
    sessions = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    Base.metadata.create_all(engine)
    first_select_finished = threading.Event()
    allow_reader = threading.Event()
    reader_state = threading.local()
    listener_state = {"paused": False}

    def pause_after_link_read(_conn, _cursor, statement, _parameters, _context, _executemany):
        if (
            getattr(reader_state, "name", "") == "reader"
            and not listener_state["paused"]
            and "document_disease_links" in statement.lower()
        ):
            listener_state["paused"] = True
            first_select_finished.set()
            assert allow_reader.wait(10), "reader was not released after the concurrent update"

    event.listen(engine, "after_cursor_execute", pause_after_link_read)
    try:
        with sessions() as db:
            db.add(
                DocumentRecord(
                    id=document_id,
                    user_id=user_id,
                    workspace_id=workspace_id,
                    filename=f"{document_id}.pdf",
                    stored_filename=f"stored-{document_id}.pdf",
                    original_filename="snapshot-paper.pdf",
                    file_extension="pdf",
                    file_type="pdf",
                    mime_type="application/pdf",
                    file_hash="file-snapshot",
                    file_path=f"/tmp/{document_id}.pdf",
                    file_size=10,
                    status="completed",
                    document_kind="research_paper",
                    language="en",
                    parsed_source_hash="parsed-snapshot",
                )
            )
            db.flush()
            db.add(
                DocumentDiseaseLinkRecord(
                    id=f"comparison-snapshot-link-{suffix}",
                    user_id=user_id,
                    workspace_id=workspace_id,
                    document_id=document_id,
                    concept_id="mesh:D000795",
                    preferred_name_en="Fabry Disease",
                    preferred_name_zh="法布雷病",
                    matched_alias="Fabry Disease",
                    ontology_version="test-v1",
                    link_source="manual_selection",
                )
            )
            db.add(
                MedicalAnalysisRunRecord(
                    id=run_before,
                    user_id=user_id,
                    workspace_id=workspace_id,
                    document_id=document_id,
                    requested_by=user_id,
                    status="succeeded",
                    source_hash="file-snapshot",
                    parsed_source_hash="parsed-snapshot",
                    analysis_key=f"comparison-snapshot-before-{suffix}",
                    is_current=True,
                )
            )
            db.flush()
            db.add(
                MedicalAnalysisResultRecord(
                    run_id=run_before,
                    report_json=_comparison_report_json("EVIDENCE-before"),
                    validation_status="validated",
                )
            )
            db.add(
                MedicalAnalysisEvidenceRecord(
                    id=f"comparison-snapshot-evidence-before-{suffix}",
                    evidence_id="EVIDENCE-before",
                    run_id=run_before,
                    finding_id="finding-before",
                    chunk_id="chunk-before",
                    section_type="results",
                    section_title="Results",
                    quoted_text="Evidence from the original analysis.",
                    page_start=2,
                    page_end=2,
                )
            )
            db.commit()

        repository = DiseaseProfileRepository(sessions, enabled=lambda: True)
        outcome: dict[str, object] = {}

        def read_comparison():
            reader_state.name = "reader"
            try:
                outcome["records"] = repository.load_comparison_inputs(
                    user_id=user_id,
                    workspace_id=workspace_id,
                    concept_id="mesh:D000795",
                    document_ids=[document_id],
                )
            except BaseException as exc:
                outcome["error"] = exc

        reader = threading.Thread(target=read_comparison)
        reader.start()
        assert first_select_finished.wait(10), "comparison reader did not reach its first SELECT"

        with sessions() as db:
            old_run = db.get(MedicalAnalysisRunRecord, run_before)
            assert old_run is not None
            old_run.is_current = False
            if change_document:
                document = db.get(DocumentRecord, document_id)
                assert document is not None
                document.parsed_source_hash = "parsed-snapshot-v2"
            db.add(
                MedicalAnalysisRunRecord(
                    id=run_after,
                    user_id=user_id,
                    workspace_id=workspace_id,
                    document_id=document_id,
                    requested_by=user_id,
                    status="succeeded",
                    source_hash="file-snapshot",
                    parsed_source_hash="parsed-snapshot-v2" if change_document else "parsed-snapshot",
                    analysis_key=f"comparison-snapshot-after-{suffix}",
                    is_current=True,
                )
            )
            db.flush()
            db.add(
                MedicalAnalysisResultRecord(
                    run_id=run_after,
                    report_json=_comparison_report_json("EVIDENCE-after"),
                    validation_status="validated",
                )
            )
            db.add(
                MedicalAnalysisEvidenceRecord(
                    id=f"comparison-snapshot-evidence-after-{suffix}",
                    evidence_id="EVIDENCE-after",
                    run_id=run_after,
                    finding_id="finding-after",
                    chunk_id="chunk-after",
                    section_type="results",
                    section_title="Results",
                    quoted_text="Evidence from the replacement analysis.",
                    page_start=3,
                    page_end=3,
                )
            )
            db.commit()

        allow_reader.set()
        reader.join(timeout=20)
        assert not reader.is_alive(), "comparison reader did not finish"
        if "error" in outcome:
            assert change_document
            assert getattr(outcome["error"], "code", "") == "comparison_source_changed"
        else:
            records = outcome["records"]
            assert records[0]["document"]["parsed_source_hash"] == "parsed-snapshot"
            assert records[0]["analyses"][0]["run"]["run_id"] == run_before
    finally:
        event.remove(engine, "after_cursor_execute", pause_after_link_read)
        with admin.begin() as db:
            db.exec_driver_sql(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        engine.dispose()
        admin.dispose()
