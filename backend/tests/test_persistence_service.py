"""Persistence foundation tests.

The DB layer is optional in local development, so these tests keep the fallback
path honest and check that document metadata maps cleanly into DB columns.
"""

from app.services import persistence_service


def test_persistence_helpers_noop_when_database_disabled(monkeypatch):
    monkeypatch.setattr(persistence_service, "db_enabled", lambda: False)

    persistence_service.save_document_record({"filename": "notes.md"})
    persistence_service.mark_document_deleted("notes.md", "local-dev")


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
