"""Parsed artifact repository tests."""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
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


def _metadata(filename="hash.md") -> dict:
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
        "user_id": "u1",
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
    )

    chunks = artifacts.list_chunks("hash.md")
    entities = artifacts.list_entities("hash.md")

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
    )

    artifacts.delete_for_document("hash.md")

    assert artifacts.list_chunks("hash.md") == []
    assert artifacts.list_entities("hash.md") == []
