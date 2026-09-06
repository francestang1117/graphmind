"""Tests for evidence-backed medical document insights."""

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.persistence import (
    DocumentRecord,
    DocumentSectionRecord,
    MedicalAnalysisEvidenceRecord,
    MedicalAnalysisRunRecord,
    MedicalDocumentProfileRecord,
    ParsedChunkRecord,
)
from app.services.medical.ai.analysis_repository import AnalysisRepository
from app.services.medical.ai.analyzer import MedicalInsightAnalyzer
from app.services.medical.ai.citation_validator import evidence_rows, validate_citations
from app.services.medical.ai.context_builder import AnalysisContext, EvidenceItem
from app.services.medical.ai.exceptions import MedicalInsightValidationError
from app.services.medical.ai.models import MedicalInsightReport
from app.services.medical.ai.provider import ExtractiveMedicalAIProvider, FakeMedicalAIProvider
from app.services.medical.ai.safety_validator import validate_safety


def _context(*items: tuple[str, str]) -> AnalysisContext:
    evidence = [
        EvidenceItem(
            evidence_id=evidence_id,
            chunk_id=f"chunk-{index}",
            section_id=f"section-{index}",
            section_type=section_type,
            section_title=section_type.title(),
            page_start=index,
            page_end=index,
            character_start=index * 100,
            character_end=index * 100 + 20,
            text=f"Source text for {evidence_id}.",
            token_count=5,
            source_index=index,
        )
        for index, (evidence_id, section_type) in enumerate(items, start=1)
    ]
    return AnalysisContext(
        title="Example paper",
        document_kind="research_paper",
        language="en",
        evidence=evidence,
    )


def _report(*evidence_ids: str) -> MedicalInsightReport:
    return MedicalInsightReport.model_validate(
        {
            "document_kind": "research_paper",
            "language": "en",
            "overview": {
                "title": "Example paper",
                "summary": "The paper reports a result.",
                "study_type": "Research paper",
                "evidence_ids": list(evidence_ids[:1]),
            },
            "key_findings": [
                {
                    "id": "finding_001",
                    "statement": "The paper reports a result.",
                    "plain_explanation": "This is what the paper says.",
                    "evidence_ids": list(evidence_ids[:1]),
                    "evidence_level": "reported_in_document",
                    "interpretation_type": "direct_statement",
                }
            ],
            "limitations": [],
            "medical_terms": [],
            "what_it_means": [],
            "what_it_does_not_mean": [],
            "questions_for_professional": [],
            "warnings": [],
        }
    )


def test_citations_require_current_evidence_and_reject_references():
    context = _context(("EVIDENCE_001", "results"), ("EVIDENCE_002", "references"))

    valid = validate_citations(_report("EVIDENCE_001"), context)
    assert valid.valid
    assert valid.coverage == 1.0
    assert evidence_rows(_report("EVIDENCE_001"), context)[0]["section_type"] == "results"

    references = validate_citations(_report("EVIDENCE_002"), context)
    assert not references.valid
    assert any("references section" in error for error in references.errors)

    unknown = validate_citations(_report("EVIDENCE_999"), context)
    assert not unknown.valid
    assert any("unknown evidence id" in error for error in unknown.errors)


def test_safety_validator_rejects_personal_treatment_instructions():
    payload = _report("EVIDENCE_001").model_dump()
    payload["key_findings"] = [
        {
            "id": "finding_001",
            "statement": "You should change your medication.",
            "plain_explanation": "This is not allowed in a document summary.",
            "evidence_ids": ["EVIDENCE_001"],
            "evidence_level": "reported_in_document",
            "interpretation_type": "inference",
        }
    ]
    report = MedicalInsightReport.model_validate(payload)
    validation = validate_safety(report)
    assert not validation.valid
    assert "treatment" in validation.errors[0]


def test_analyzer_repairs_one_invalid_provider_response():
    invalid = _report("EVIDENCE_001").model_dump()
    invalid["overview"]["evidence_ids"] = []
    valid = _report("EVIDENCE_001").model_dump()
    provider = FakeMedicalAIProvider(payloads=[invalid, valid])

    output = MedicalInsightAnalyzer(provider=provider).run(
        [{"id": "chunk-1", "text": "The result was reported.", "metadata": {"section_type": "results"}}],
        title="Example paper",
        document_kind="research_paper",
        language="en",
    )

    assert output.citations.valid
    assert len(provider.calls) == 2
    assert output.report.warnings[-1] == "not_medical_advice"


def test_analyzer_does_not_retry_more_than_once_after_invalid_repair():
    invalid = _report("EVIDENCE_001").model_dump()
    invalid["overview"]["evidence_ids"] = []
    provider = FakeMedicalAIProvider(payloads=[invalid, invalid, invalid])

    with pytest.raises(MedicalInsightValidationError):
        MedicalInsightAnalyzer(provider=provider).run(
            [{"id": "chunk-1", "text": "The result was reported.", "metadata": {"section_type": "results"}}],
            title="Example paper",
            document_kind="research_paper",
            language="en",
        )

    assert len(provider.calls) == 2


def _repository():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(bind=engine)
    sessions = sessionmaker(bind=engine, autoflush=False, future=True)
    return engine, sessions, AnalysisRepository(sessions, enabled=lambda: True)


def _paper_rows(sessions):
    now = datetime.now(timezone.utc)
    with sessions() as db:
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
                file_hash="a" * 64,
                file_path="/tmp/paper.pdf",
                file_size=100,
                status="indexed",
                created_at=now,
                modified_at=now,
            )
        )
        db.add(
            MedicalDocumentProfileRecord(
                id="profile-1",
                user_id="user-1",
                workspace_id="workspace-1",
                document_id="document-1",
                document_kind="research_paper",
                language="en",
                confidence=0.95,
            )
        )
        db.add(
            DocumentSectionRecord(
                id="section-1",
                user_id="user-1",
                workspace_id="workspace-1",
                document_id="document-1",
                section_type="results",
                original_title="Results",
                ordinal=1,
                page_start=2,
                page_end=2,
                char_start=0,
                char_end=28,
                text="The result was reported.",
                language="en",
            )
        )
        db.add(
            ParsedChunkRecord(
                id="chunk-1",
                user_id="user-1",
                workspace_id="workspace-1",
                document_id="document-1",
                chunk_index=0,
                chunk_type="medical_section",
                text="The result was reported.",
                metadata_json='{"section_type":"results","section_title":"Results","page_start":2,"page_end":2,"section_id":"section-1"}',
            )
        )
        db.commit()


def test_repository_persists_citations_and_filters_stale_source_versions():
    engine, sessions, repository = _repository()
    try:
        _paper_rows(sessions)
        run, created = repository.create_or_reuse(
            document_id="document-1",
            user_id="user-1",
            workspace_id="workspace-1",
            source_hash="a" * 64,
            requested_by="user-1",
            provider="extractive",
            model_name="extractive-v1",
            prompt_version="medical-insights-v1",
            schema_version="medical-insights-v1",
        )
        assert created
        claimed = repository.mark_running(run["run_id"])
        assert claimed["status"] == "running"

        output = MedicalInsightAnalyzer(provider=ExtractiveMedicalAIProvider()).run(
            [{"id": "chunk-1", "text": "The result was reported.", "metadata": {"section_type": "results", "section_title": "Results", "page_start": 2, "page_end": 2, "section_id": "section-1"}}],
            sections=[{"id": "section-1", "section_type": "results", "original_title": "Results", "page_start": 2, "page_end": 2}],
            title="paper.pdf",
            document_kind="research_paper",
            language="en",
        )
        saved = repository.save_success(run["run_id"], output)
        assert saved["status"] == "succeeded"
        assert saved["evidence"][0]["section_type"] == "results"
        assert saved["evidence"][0]["section_title"] == "Results"

        with sessions() as db:
            document = db.get(DocumentRecord, "document-1")
            document.file_hash = "b" * 64
            db.commit()

        assert repository.get_latest("document-1", "user-1", "workspace-1") is None
        stale = repository.get_run(run["run_id"], "user-1", "workspace-1")
        assert stale["outdated"] is True
        assert stale["is_current"] is False

        with sessions() as db:
            assert len(db.scalars(select(MedicalAnalysisRunRecord)).all()) == 1
            assert len(db.scalars(select(MedicalAnalysisEvidenceRecord)).all()) >= 1
    finally:
        engine.dispose()
