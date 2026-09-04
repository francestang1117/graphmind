"""Parsed artifact repository tests."""

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.persistence import (
    DocumentSectionRecord,
    MedicalDocumentProfileRecord,
    ParsedChunkRecord,
    ParsedEntityRecord,
)
import app.services.parsed_artifact_repository as artifact_module
from app.services.document_repository import DocumentRepository
from app.services.parsed_artifact_repository import ParsedArtifactRepository


def _repos():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    enabled = lambda: True
    return (
        DocumentRepository(session_factory=session_factory, enabled=enabled),
        ParsedArtifactRepository(session_factory=session_factory, enabled=enabled),
    )


def _metadata(filename="hash.md", user_id="u1") -> dict:
    return {
        "filename": filename,
        "stored_filename": filename,
        "original_filename": "notes.md",
        "file_size": 42,
        "file_extension": ".md",
        "file_type": ".md",
        "file_hash": "abc123",
        "mime_type": "text/markdown",
        "file_path": f"/tmp/{filename}",
        "user_id": user_id,
        "created_at": "2026-05-02T00:00:00+00:00",
        "modified_at": "2026-05-02T00:00:01+00:00",
    }


def test_artifacts_replace_chunks_and_entities_for_document():
    docs, artifacts = _repos()
    docs.save_metadata(_metadata())

    artifacts.replace_for_document(
        "hash.md",
        {
            "chunks": [
                {"text": "First chunk", "type": "section", "section": "Intro"},
                {"text": "Second chunk", "type": "code", "language": "python"},
            ]
        },
        [
            {"text": "Python", "label": "PROGRAMMING_LANGUAGE", "confidence": 0.9},
            {"text": "Python", "label": "PROGRAMMING_LANGUAGE", "confidence": 0.8},
            {"text": "FastAPI", "label": "FRAMEWORK", "source": "domain"},
        ],
        user_id="u1",
    )

    chunks = artifacts.list_chunks("hash.md", user_id="u1")
    entities = artifacts.list_entities("hash.md", user_id="u1")

    assert [chunk["text"] for chunk in chunks] == ["First chunk", "Second chunk"]
    assert chunks[0]["metadata"]["section"] == "Intro"
    assert {entity["normalized"] for entity in entities} == {"Python", "FastAPI"}
    assert all(entity["user_id"] == "u1" for entity in entities)


def test_artifacts_delete_for_document():
    docs, artifacts = _repos()
    docs.save_metadata(_metadata())
    artifacts.replace_for_document(
        "hash.md",
        {"chunks": [{"text": "First chunk"}]},
        [{"text": "Python", "label": "PROGRAMMING_LANGUAGE"}],
        user_id="u1",
    )

    artifacts.delete_for_document("hash.md", user_id="u1")

    assert artifacts.list_chunks("hash.md", user_id="u1") == []
    assert artifacts.list_entities("hash.md", user_id="u1") == []


def test_artifacts_are_isolated_when_users_upload_the_same_file():
    docs, artifacts = _repos()
    first = _metadata("same.md", user_id="u1")
    second = _metadata("same.md", user_id="u2")
    docs.save_metadata(first)
    docs.save_metadata(second)

    artifacts.replace_for_document(
        "same.md",
        {"chunks": [{"text": "User one"}]},
        [{"text": "Python", "label": "PROGRAMMING_LANGUAGE"}],
        user_id="u1",
    )
    artifacts.replace_for_document(
        "same.md",
        {"chunks": [{"text": "User two"}]},
        [{"text": "FastAPI", "label": "FRAMEWORK"}],
        user_id="u2",
    )

    assert first["document_id"] != second["document_id"]
    assert [item["text"] for item in artifacts.list_chunks("same.md", user_id="u1")] == ["User one"]
    assert [item["text"] for item in artifacts.list_chunks("same.md", user_id="u2")] == ["User two"]
    assert artifacts.list_entities("same.md", user_id="u1")[0]["text"] == "Python"
    assert artifacts.list_entities("same.md", user_id="u2")[0]["text"] == "FastAPI"

    artifacts.delete_for_document("same.md", user_id="u1")
    assert artifacts.list_chunks("same.md", user_id="u1") == []
    assert artifacts.list_chunks("same.md", user_id="u2")[0]["text"] == "User two"


def test_artifacts_ignore_late_write_after_document_deletion():
    docs, artifacts = _repos()
    docs.save_metadata(_metadata())
    artifacts.replace_for_document(
        "hash.md",
        {"chunks": [{"text": "Old content"}]},
        [{"text": "Python", "label": "PROGRAMMING_LANGUAGE"}],
        user_id="u1",
    )

    docs.mark_deleted("hash.md", "u1")
    artifacts.delete_for_document("hash.md", user_id="u1")
    artifacts.replace_for_document(
        "hash.md",
        {"chunks": [{"text": "Late content"}]},
        [{"text": "FastAPI", "label": "FRAMEWORK"}],
        user_id="u1",
    )

    with artifacts.session_factory() as db:
        assert db.scalars(select(ParsedChunkRecord)).all() == []
        assert db.scalars(select(ParsedEntityRecord)).all() == []


def test_parse_bundle_rolls_back_all_rows_when_later_write_fails(monkeypatch):
    docs, artifacts = _repos()
    docs.save_metadata(_metadata())

    old_analysis = {
        "document_kind": "research_paper",
        "language": "en",
        "confidence": 0.8,
        "classifier_version": "medical-rules-v1",
        "signals": [],
        "warnings": [],
        "missing_sections": [],
    }
    old_sections = [
        {
            "section_type": "results",
            "original_title": "Results",
            "page_start": 1,
            "page_end": 1,
            "text": "Old result",
            "language": "en",
            "confidence": 0.8,
            "metadata": {},
        }
    ]
    assert artifacts.replace_parse_bundle(
        "hash.md",
        {"chunks": [{"text": "Old chunk", "type": "section"}]},
        [{"text": "Old concept", "label": "CONCEPT"}],
        old_analysis,
        old_sections,
        user_id="u1",
    )

    real_medical_write = artifact_module.replace_analysis_in_session

    def fail_medical_write(*args, **kwargs):
        assert real_medical_write(*args, **kwargs)
        raise RuntimeError("simulated later persistence failure")

    monkeypatch.setattr(
        artifact_module,
        "replace_analysis_in_session",
        fail_medical_write,
    )

    with pytest.raises(RuntimeError, match="simulated later persistence failure"):
        artifacts.replace_parse_bundle(
            "hash.md",
            {"chunks": [{"text": "New chunk", "type": "section"}]},
            [{"text": "New concept", "label": "CONCEPT"}],
            {**old_analysis, "confidence": 0.95},
            [{**old_sections[0], "text": "New result"}],
            user_id="u1",
        )

    assert [item["text"] for item in artifacts.list_chunks("hash.md", user_id="u1")] == [
        "Old chunk"
    ]
    with artifacts.session_factory() as db:
        profile = db.scalars(select(MedicalDocumentProfileRecord)).one()
        section = db.scalars(select(DocumentSectionRecord)).one()
        assert profile.confidence == 0.8
        assert section.text == "Old result"
