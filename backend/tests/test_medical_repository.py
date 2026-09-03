"""Database tests for medical profiles and paper sections."""

from datetime import datetime, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.core.workspace import default_workspace_id
from app.models.persistence import (
    DocumentRecord,
    DocumentSectionRecord,
    MedicalDocumentProfileRecord,
)
from app.services.medical.repository import MedicalRepository


def _setup():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(bind=engine)
    sessions = sessionmaker(bind=engine, autoflush=False, future=True)
    return engine, sessions, MedicalRepository(sessions, enabled=lambda: True)


def _document(user_id="user-a", workspace_id="workspace-a") -> DocumentRecord:
    return DocumentRecord(
        id="document-a",
        user_id=user_id,
        workspace_id=workspace_id,
        filename="paper.pdf",
        stored_filename="paper.pdf",
        original_filename="paper.pdf",
        file_extension=".pdf",
        file_type=".pdf",
        mime_type="application/pdf",
        file_hash="a" * 64,
        file_path="/tmp/paper.pdf",
        file_size=10,
        status="indexed",
    )


def _analysis(text="Paper result") -> tuple[dict, list[dict]]:
    analysis = {
        "document_kind": "research_paper",
        "confidence": 0.9,
        "language": "en",
        "classifier_version": "medical-rules-v1",
        "signals": ["found_results_heading"],
        "warnings": [],
        "missing_sections": ["limitations"],
    }
    sections = [
        {
            "section_type": "results",
            "original_title": "Results",
            "page_start": 3,
            "page_end": 3,
            "char_start": 10,
            "char_end": 10 + len(text),
            "text": text,
            "language": "en",
            "confidence": 0.96,
            "secondary_types": [],
            "chunk_count": 1,
            "metadata": {"evidence_role": "study_result"},
        }
    ]
    return analysis, sections


def test_analysis_replace_is_idempotent_and_workspace_scoped():
    _, sessions, repository = _setup()
    with sessions() as db:
        db.add(_document())
        db.commit()

    analysis, sections = _analysis()
    assert repository.replace_analysis(
        "document-a", analysis, sections, user_id="user-a", workspace_id="workspace-a"
    )
    updated_analysis, updated_sections = _analysis("Updated result")
    assert repository.replace_analysis(
        "document-a",
        updated_analysis,
        updated_sections,
        user_id="user-a",
        workspace_id="workspace-a",
    )

    saved = repository.get_analysis(
        "document-a", user_id="user-a", workspace_id="workspace-a"
    )
    assert saved["sections"][0]["text"] == "Updated result"
    with sessions() as db:
        assert db.scalars(select(MedicalDocumentProfileRecord)).all().__len__() == 1
        assert db.scalars(select(DocumentSectionRecord)).all().__len__() == 1

    assert repository.get_analysis(
        "document-a", user_id="user-b", workspace_id="workspace-a"
    ) is None
    assert repository.get_analysis(
        "document-a", user_id="user-a", workspace_id="workspace-b"
    ) is None


def test_deleted_document_cannot_receive_late_analysis_and_cleanup_is_repeatable():
    _, sessions, repository = _setup()
    with sessions() as db:
        db.add(_document())
        db.commit()

    analysis, sections = _analysis()
    assert repository.replace_analysis(
        "document-a", analysis, sections, user_id="user-a", workspace_id="workspace-a"
    )
    with sessions() as db:
        document = db.get(DocumentRecord, "document-a")
        document.deleted_at = datetime.now(timezone.utc)
        db.commit()

    repository.delete_for_document(
        "document-a", user_id="user-a", workspace_id="workspace-a"
    )
    repository.delete_for_document(
        "document-a", user_id="user-a", workspace_id="workspace-a"
    )
    assert not repository.replace_analysis(
        "document-a", analysis, sections, user_id="user-a", workspace_id="workspace-a"
    )

    with sessions() as db:
        assert db.scalars(select(MedicalDocumentProfileRecord)).all() == []
        assert db.scalars(select(DocumentSectionRecord)).all() == []


def test_legacy_document_without_workspace_uses_the_default_scope():
    _, sessions, repository = _setup()
    with sessions() as db:
        db.add(_document(workspace_id=None))
        db.commit()

    analysis, sections = _analysis()
    assert repository.replace_analysis(
        "document-a", analysis, sections, user_id="user-a"
    )

    saved = repository.get_analysis("document-a", user_id="user-a")
    assert saved["workspace_id"] == default_workspace_id("user-a")
