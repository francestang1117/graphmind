"""Database-backed document repository tests."""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.services.document_repository import DocumentRepository


def _repo() -> DocumentRepository:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    return DocumentRepository(session_factory=session_factory, enabled=lambda: True)


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


def test_repository_saves_lists_and_gets_by_user():
    repo = _repo()
    repo.save_metadata(_metadata(user_id="u1"))
    repo.save_metadata(_metadata(filename="other.md", user_id="u2"))

    listed = repo.list("u1")
    fetched = repo.get("hash.md", "u1")

    assert [item["filename"] for item in listed] == ["hash.md"]
    assert fetched["original_filename"] == "notes.md"
    assert fetched["user_id"] == "u1"
    assert repo.get("hash.md", "u2") is None


def test_repository_soft_delete_hides_document():
    repo = _repo()
    repo.save_metadata(_metadata())

    repo.mark_deleted("hash.md", "u1")

    assert repo.list("u1") == []
    assert repo.get("hash.md", "u1") is None
    assert repo.has_any("u1") is True
    assert repo.has_record("hash.md", "u1") is True


def test_repository_updates_existing_record():
    repo = _repo()
    metadata = _metadata()
    repo.save_metadata(metadata)

    metadata["original_filename"] = "renamed.md"
    metadata["file_size"] = 99
    repo.save_metadata(metadata)

    fetched = repo.get("hash.md", "u1")
    assert fetched["original_filename"] == "renamed.md"
    assert fetched["file_size"] == 99


def test_repository_has_any_is_user_scoped():
    repo = _repo()
    repo.save_metadata(_metadata(user_id="u1"))

    assert repo.has_any("u1") is True
    assert repo.has_any("u2") is False
