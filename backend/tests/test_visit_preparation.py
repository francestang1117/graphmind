"""Regression tests for persistent clinician questions and visit briefs."""

from __future__ import annotations

from datetime import datetime, timezone
import json

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.persistence import (
    ClinicianQuestionRecord,
    DocumentRecord,
    MedicalAnalysisEvidenceRecord,
    MedicalAnalysisResultRecord,
    MedicalAnalysisRunRecord,
    VisitBriefItemRecord,
    VisitBriefRecord,
    WorkspaceRecord,
)
from app.services.medical.ai.analysis_repository import AnalysisRepository, _normalize_saved_report
from app.services.medical.visit_preparation.exceptions import VisitPreparationError
from app.services.medical.visit_preparation.repository import VisitPreparationRepository
from app.services.medical.visit_preparation.service import VisitPreparationService


def _session_factory() -> tuple[object, sessionmaker]:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(bind=engine)
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
    return engine, sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def _report_payload() -> dict:
    payload = {
        "schema_version": "medical-insights-v3",
        "document_kind": "research_paper",
        "language": "en",
        "overview": {
            "title": "Example paper",
            "summary": "The paper reports a result.",
            "study_type": "Research paper",
            "evidence_ids": ["EVIDENCE_001"],
        },
        "study_methods": {
            "population": {
                "value": "The study included adults with the condition.",
                "support_status": "supported",
                "evidence_ids": ["EVIDENCE_001"],
            },
            "design": {
                "value": "A prospective observational study.",
                "support_status": "supported",
                "evidence_ids": ["EVIDENCE_001"],
            },
        },
        "key_findings": [
            {
                "id": "finding_001",
                "statement": "The study reported a result.",
                "plain_explanation": "This is what the paper says.",
                "evidence_ids": ["EVIDENCE_001"],
                "evidence_level": "reported_in_document",
                "interpretation_type": "direct_statement",
            }
        ],
        "limitations": [],
        "medical_terms": [],
        "what_it_means": [],
        "what_it_does_not_mean": [],
        "applicability": [],
        "future_research": [],
        "question_suggestions": [
            {
                "id": "question_001",
                "question": "",
                "rationale": "",
                "category": "applicability",
                "topic": "study_population",
                "source_kind": "study_methods",
                "source_id": "population",
                "evidence_ids": [],
                "interpretation_type": "inference",
            }
        ],
        "questions_for_professional": [],
        "warnings": [],
    }
    return _normalize_saved_report(payload, "medical-insights-v3")


def _seed(session_factory: sessionmaker) -> None:
    now = datetime.now(timezone.utc)
    report = _report_payload()
    with session_factory() as db:
        db.add(
            WorkspaceRecord(
                id="workspace-1",
                user_id="user-1",
                name="Research project",
                research_question="How should this result be discussed?",
            )
        )
        db.add(
            DocumentRecord(
                id="document-1",
                user_id="user-1",
                workspace_id="workspace-1",
                filename="paper.pdf",
                stored_filename="paper.pdf",
                original_filename="paper.pdf",
                file_extension=".pdf",
                file_type=".pdf",
                mime_type="application/pdf",
                file_hash="f" * 64,
                parsed_source_hash="p" * 64,
                file_path="/tmp/paper.pdf",
                file_size=100,
                status="indexed",
                created_at=now,
                modified_at=now,
            )
        )
        db.add(
            MedicalAnalysisRunRecord(
                id="analysis-1",
                user_id="user-1",
                workspace_id="workspace-1",
                document_id="document-1",
                requested_by="user-1",
                status="succeeded",
                source_hash="f" * 64,
                parsed_source_hash="p" * 64,
                analysis_key="single_document_insight:paper",
                provider="extractive",
                model_name="extractive-v1",
                prompt_version="medical-insights-v3",
                schema_version="medical-insights-v3",
                error_code="",
                error_message="",
                is_current=True,
                created_at=now,
                completed_at=now,
                updated_at=now,
            )
        )
        # The legacy models intentionally do not declare ORM relationships;
        # commit the foreign-key parents before adding result/evidence rows so
        # SQLite and PostgreSQL exercise the same referential ordering.
        db.commit()
        db.add(
            MedicalAnalysisResultRecord(
                run_id="analysis-1",
                report_json=json.dumps(report, ensure_ascii=False),
                citation_coverage=1.0,
                validation_status="validated",
                warnings_json="[]",
                created_at=now,
            )
        )
        db.add(
            MedicalAnalysisEvidenceRecord(
                id="evidence-row-1",
                evidence_id="EVIDENCE_001",
                run_id="analysis-1",
                finding_id="finding_001",
                chunk_id="chunk-1",
                section_id="section-1",
                section_type="methods",
                section_title="Methods",
                page_start=2,
                page_end=3,
                quoted_text="The study included adults with the condition.",
                character_start=100,
                character_end=147,
            )
        )
        db.commit()


def _service(session_factory: sessionmaker) -> VisitPreparationService:
    return VisitPreparationService(
        repository=VisitPreparationRepository(session_factory, enabled=lambda: True),
        analysis_repository=AnalysisRepository(session_factory, enabled=lambda: True),
    )


def _add_second_document(session_factory: sessionmaker) -> None:
    """Create a second valid source so ordering tests span documents."""
    now = datetime.now(timezone.utc)
    with session_factory() as db:
        db.add(
            DocumentRecord(
                id="document-2",
                user_id="user-1",
                workspace_id="workspace-1",
                filename="second-paper.pdf",
                stored_filename="second-paper.pdf",
                original_filename="second-paper.pdf",
                file_extension=".pdf",
                file_type=".pdf",
                mime_type="application/pdf",
                file_hash="g" * 64,
                parsed_source_hash="q" * 64,
                file_path="/tmp/second-paper.pdf",
                file_size=100,
                status="indexed",
                created_at=now,
                modified_at=now,
            )
        )
        db.add(
            MedicalAnalysisRunRecord(
                id="analysis-2",
                user_id="user-1",
                workspace_id="workspace-1",
                document_id="document-2",
                requested_by="user-1",
                status="succeeded",
                source_hash="g" * 64,
                parsed_source_hash="q" * 64,
                analysis_key="single_document_insight:second-paper",
                provider="extractive",
                model_name="extractive-v1",
                prompt_version="medical-insights-v3",
                schema_version="medical-insights-v3",
                error_code="",
                error_message="",
                is_current=True,
                created_at=now,
                completed_at=now,
                updated_at=now,
            )
        )
        db.commit()
        db.add(
            MedicalAnalysisResultRecord(
                run_id="analysis-2",
                report_json=json.dumps(_report_payload(), ensure_ascii=False),
                citation_coverage=1.0,
                validation_status="validated",
                warnings_json="[]",
                created_at=now,
            )
        )
        db.add(
            MedicalAnalysisEvidenceRecord(
                id="evidence-row-2",
                evidence_id="EVIDENCE_001",
                run_id="analysis-2",
                finding_id="finding_001",
                chunk_id="chunk-2",
                section_id="section-2",
                section_type="methods",
                section_title="Methods",
                page_start=4,
                page_end=4,
                quoted_text="The second study included adults with the condition.",
                character_start=200,
                character_end=253,
            )
        )
        db.commit()


def test_save_question_is_server_bound_and_idempotent():
    engine, sessions = _session_factory()
    try:
        _seed(sessions)
        service = _service(sessions)

        item, created, source_refreshed = service.save_question(
            user_id="user-1",
            workspace_id="workspace-1",
            analysis_run_id="analysis-1",
            suggestion_id="question_001",
        )
        again, created_again, source_refreshed_again = service.save_question(
            user_id="user-1",
            workspace_id="workspace-1",
            analysis_run_id="analysis-1",
            suggestion_id="question_001",
        )

        assert created is True
        assert source_refreshed is False
        assert created_again is False
        assert source_refreshed_again is False
        assert item["id"] == again["id"]
        assert item["question"] == (
            "Which people were included in this study, and who was not included?"
        )
        assert item["evidence_ids"] == ["EVIDENCE_001"]
        assert item["source_status"] == "current"
        with sessions() as db:
            assert db.scalar(select(func.count()).select_from(ClinicianQuestionRecord)) == 1
    finally:
        engine.dispose()


def test_refreshing_question_reports_changed_source_and_preserves_user_state():
    engine, sessions = _session_factory()
    try:
        _seed(sessions)
        service = _service(sessions)
        item, _, _ = service.save_question(
            user_id="user-1",
            workspace_id="workspace-1",
            analysis_run_id="analysis-1",
            suggestion_id="question_001",
        )
        service.update_question(
            item["id"],
            user_id="user-1",
            workspace_id="workspace-1",
            status="asked",
            priority=None,
            position=None,
            user_note="Ask at the next visit",
            expected_version=1,
        )

        with sessions() as db:
            run = db.get(MedicalAnalysisRunRecord, "analysis-1")
            report = json.loads(db.get(MedicalAnalysisResultRecord, "analysis-1").report_json)
            report["question_suggestions"][0]["source_id"] = "design"
            db.get(MedicalAnalysisResultRecord, "analysis-1").report_json = json.dumps(report)
            run.analysis_key = "single_document_insight:paper:v2"
            db.commit()

        refreshed, created, source_refreshed = service.save_question(
            user_id="user-1",
            workspace_id="workspace-1",
            analysis_run_id="analysis-1",
            suggestion_id="question_001",
        )
        assert created is False
        assert source_refreshed is True
        assert refreshed["source_id"] == "design"
        assert refreshed["status"] == "asked"
        assert refreshed["user_note"] == "Ask at the next visit"
    finally:
        engine.dispose()


def test_question_updates_use_optimistic_version_and_notes_are_plain_text():
    engine, sessions = _session_factory()
    try:
        _seed(sessions)
        service = _service(sessions)
        item, _, _ = service.save_question(
            user_id="user-1",
            workspace_id="workspace-1",
            analysis_run_id="analysis-1",
            suggestion_id="question_001",
        )

        updated = service.update_question(
            item["id"],
            user_id="user-1",
            workspace_id="workspace-1",
            status="asked",
            priority=1,
            position=3,
            user_note="<b>Ask about follow-up</b>",
            expected_version=1,
        )
        assert updated["version"] == 2
        assert updated["status"] == "asked"
        assert updated["user_note"] == "Ask about follow-up"

        with pytest.raises(VisitPreparationError) as exc:
            service.update_question(
                item["id"],
                user_id="user-1",
                workspace_id="workspace-1",
                status="answered",
                priority=None,
                position=None,
                user_note=None,
                expected_version=1,
            )
        assert exc.value.code == "clinician_question_version_conflict"
    finally:
        engine.dispose()


def test_visit_brief_copies_current_evidence_and_only_requested_notes():
    engine, sessions = _session_factory()
    try:
        _seed(sessions)
        service = _service(sessions)
        question, _, _ = service.save_question(
            user_id="user-1",
            workspace_id="workspace-1",
            analysis_run_id="analysis-1",
            suggestion_id="question_001",
        )
        service.update_question(
            question["id"],
            user_id="user-1",
            workspace_id="workspace-1",
            status=None,
            priority=None,
            position=None,
            user_note="Remember to ask about eligibility.",
            expected_version=1,
        )

        brief = service.create_visit_brief(
            user_id="user-1",
            workspace_id="workspace-1",
            question_ids=[question["id"]],
            include_user_notes=True,
        )

        assert brief["disclaimer"].startswith("This visit preparation sheet")
        assert brief["items"][0]["user_note"] == "Remember to ask about eligibility."
        assert brief["items"][0]["evidence"][0]["page_start"] == 2
        assert brief["items"][0]["evidence"][0]["section_type"] == "methods"
        assert brief["items"][0]["evidence"][0]["character_start"] == 100
        assert brief["items"][0]["document_title"] == "paper.pdf"
        assert brief["items"][0]["parsed_source_hash"] == "p" * 64
    finally:
        engine.dispose()


def test_question_positions_span_documents_and_reorder_is_atomic():
    engine, sessions = _session_factory()
    try:
        _seed(sessions)
        _add_second_document(sessions)
        service = _service(sessions)
        first, _, _ = service.save_question(
            user_id="user-1",
            workspace_id="workspace-1",
            analysis_run_id="analysis-1",
            suggestion_id="question_001",
        )
        second, _, _ = service.save_question(
            user_id="user-1",
            workspace_id="workspace-1",
            analysis_run_id="analysis-2",
            suggestion_id="question_001",
        )

        assert first["position"] == 0
        assert second["position"] == 1
        reordered = service.reorder_questions(
            question_id=second["id"],
            target_question_id=first["id"],
            user_id="user-1",
            workspace_id="workspace-1",
            expected_version=second["version"],
            target_expected_version=first["version"],
        )
        assert {item["id"] for item in reordered} == {first["id"], second["id"]}
        with sessions() as db:
            positions = dict(
                db.execute(
                    select(ClinicianQuestionRecord.id, ClinicianQuestionRecord.position)
                ).all()
            )
        assert positions[second["id"]] == 0
        assert positions[first["id"]] == 1

        with pytest.raises(VisitPreparationError) as exc:
            service.reorder_questions(
                question_id=second["id"],
                target_question_id=first["id"],
                user_id="user-1",
                workspace_id="workspace-1",
                expected_version=second["version"],
                target_expected_version=first["version"],
            )
        assert exc.value.code == "clinician_question_version_conflict"
        with sessions() as db:
            positions_after_conflict = dict(
                db.execute(
                    select(ClinicianQuestionRecord.id, ClinicianQuestionRecord.position)
                ).all()
            )
        assert positions_after_conflict == positions
    finally:
        engine.dispose()


def test_outdated_question_cannot_be_added_to_a_brief():
    engine, sessions = _session_factory()
    try:
        _seed(sessions)
        service = _service(sessions)
        question, _, _ = service.save_question(
            user_id="user-1",
            workspace_id="workspace-1",
            analysis_run_id="analysis-1",
            suggestion_id="question_001",
        )
        with sessions() as db:
            db.get(DocumentRecord, "document-1").parsed_source_hash = "n" * 64
            db.commit()

        with pytest.raises(VisitPreparationError) as exc:
            service.create_visit_brief(
                user_id="user-1",
                workspace_id="workspace-1",
                question_ids=[question["id"]],
                include_user_notes=False,
            )
        assert exc.value.code == "visit_brief_source_outdated"
    finally:
        engine.dispose()


def test_questions_are_scoped_and_document_cleanup_removes_copied_content():
    engine, sessions = _session_factory()
    try:
        _seed(sessions)
        service = _service(sessions)
        question, _, _ = service.save_question(
            user_id="user-1",
            workspace_id="workspace-1",
            analysis_run_id="analysis-1",
            suggestion_id="question_001",
        )
        brief = service.create_visit_brief(
            user_id="user-1",
            workspace_id="workspace-1",
            question_ids=[question["id"]],
            include_user_notes=False,
        )

        assert service.list_questions(user_id="user-1", workspace_id="other-workspace")["total"] == 0
        assert service.get_brief(brief["id"], user_id="user-2", workspace_id="workspace-1") is None

        service.repository.delete_for_document(
            "document-1",
            user_id="user-1",
            workspace_id="workspace-1",
        )
        with sessions() as db:
            assert db.scalar(select(func.count()).select_from(ClinicianQuestionRecord)) == 0
            assert db.scalar(select(func.count()).select_from(VisitBriefItemRecord)) == 0
            assert db.scalar(select(func.count()).select_from(VisitBriefRecord)) == 0
    finally:
        engine.dispose()


def test_invalid_analysis_result_is_not_a_current_source():
    engine, sessions = _session_factory()
    try:
        _seed(sessions)
        service = _service(sessions)
        question, _, _ = service.save_question(
            user_id="user-1",
            workspace_id="workspace-1",
            analysis_run_id="analysis-1",
            suggestion_id="question_001",
        )
        with sessions() as db:
            db.get(MedicalAnalysisResultRecord, "analysis-1").validation_status = "rejected"
            db.commit()
        listed = service.list_questions(user_id="user-1", workspace_id="workspace-1")
        assert listed["items"][0]["source_status"] == "unavailable"
        with pytest.raises(VisitPreparationError) as exc:
            service.create_visit_brief(
                user_id="user-1",
                workspace_id="workspace-1",
                question_ids=[question["id"]],
                include_user_notes=False,
            )
        assert exc.value.code == "visit_brief_source_outdated"
    finally:
        engine.dispose()


def test_missing_live_evidence_makes_source_unavailable():
    engine, sessions = _session_factory()
    try:
        _seed(sessions)
        service = _service(sessions)
        question, _, _ = service.save_question(
            user_id="user-1",
            workspace_id="workspace-1",
            analysis_run_id="analysis-1",
            suggestion_id="question_001",
        )
        with sessions() as db:
            db.query(MedicalAnalysisEvidenceRecord).delete()
            db.commit()

        listed = service.list_questions(user_id="user-1", workspace_id="workspace-1")
        assert listed["items"][0]["source_status"] == "unavailable"
        with pytest.raises(VisitPreparationError) as exc:
            service.create_visit_brief(
                user_id="user-1",
                workspace_id="workspace-1",
                question_ids=[question["id"]],
                include_user_notes=False,
            )
        assert exc.value.code == "visit_brief_source_outdated"
    finally:
        engine.dispose()


def test_unscoped_document_cleanup_uses_the_document_workspace():
    engine, sessions = _session_factory()
    try:
        _seed(sessions)
        service = _service(sessions)
        question, _, _ = service.save_question(
            user_id="user-1",
            workspace_id="workspace-1",
            analysis_run_id="analysis-1",
            suggestion_id="question_001",
        )
        service.create_visit_brief(
            user_id="user-1",
            workspace_id="workspace-1",
            question_ids=[question["id"]],
            include_user_notes=False,
        )

        service.repository.delete_for_document("document-1", user_id="user-1")

        with sessions() as db:
            assert db.scalar(select(func.count()).select_from(ClinicianQuestionRecord)) == 0
            assert db.scalar(select(func.count()).select_from(VisitBriefItemRecord)) == 0
            assert db.scalar(select(func.count()).select_from(VisitBriefRecord)) == 0
    finally:
        engine.dispose()
