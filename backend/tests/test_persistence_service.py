"""Persistence foundation tests.

The DB layer is optional in local development, so these tests keep the fallback
path honest and check that document metadata maps cleanly into DB columns.
"""

from app.services import persistence_service


def test_oauth_identity_round_trip(monkeypatch):
    from datetime import datetime, timezone

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.core.database import Base
    from app.models.persistence import UserRecord

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, future=True)
    monkeypatch.setattr(persistence_service, "SessionLocal", session_factory)
    monkeypatch.setattr(persistence_service, "db_enabled", lambda: True)

    with session_factory() as db:
        db.add(
            UserRecord(
                id="u1",
                email="octo@example.com",
                name="Octo Cat",
                hashed_password="",
                created_at=datetime.now(timezone.utc),
            )
        )
        db.commit()

    persistence_service.save_oauth_identity("github", "991122", "u1")
    user = persistence_service.load_user_by_oauth("github", "991122")

    assert user["id"] == "u1"
    assert user["email"] == "octo@example.com"


def test_persistence_helpers_noop_when_database_disabled(monkeypatch):
    monkeypatch.setattr(persistence_service, "db_enabled", lambda: False)

    persistence_service.save_document_record({"filename": "notes.md"})
    persistence_service.mark_document_deleted("notes.md", "local-dev")
    persistence_service.save_oauth_identity("github", "123", "u1")
    assert persistence_service.load_user_record(email="user@example.com") is None
    assert persistence_service.load_user_by_oauth("github", "123") is None


def test_document_metadata_maps_to_record_values():
    values = persistence_service._document_values(
        {
            "user_id": "u1",
            "filename": "hash.md",
            "stored_filename": "hash.md",
            "original_filename": "notes.md",
            "file_extension": ".md",
            "file_type": ".md",
            "mime_type": "text/markdown",
            "file_hash": "abc",
            "file_path": "/tmp/hash.md",
            "file_size": 123,
            "created_at": "2026-05-02T00:00:00+00:00",
            "modified_at": "2026-05-02T00:00:01+00:00",
        }
    )

    assert values["user_id"] == "u1"
    assert values["original_filename"] == "notes.md"
    assert values["file_hash"] == "abc"
    assert values["status"] == "uploaded"
    assert values["deleted_at"] is None
