"""Document service behavior that spans metadata and file storage."""

from app.services.document_service import DocumentService


class MissingFileStorage:
    def delete_file(self, filename, user_id=None):
        return False


class StaleDocumentRepository:
    def __init__(self):
        self.deleted = []

    def available(self):
        return True

    def get(self, filename, user_id):
        return {"filename": filename, "user_id": user_id}

    def mark_deleted(self, filename, user_id):
        self.deleted.append((filename, user_id))


def test_delete_soft_deletes_stale_database_record(monkeypatch):
    repository = StaleDocumentRepository()
    service = DocumentService(
        storage=MissingFileStorage(),
        repository=repository,
        use_database=True,
        virus_scan_enabled=False,
    )
    monkeypatch.setattr(
        "app.services.parsed_artifact_repository.parsed_artifact_repository.delete_for_document",
        lambda filename: None,
    )
    monkeypatch.setattr(
        "app.services.graph_repository.graph_repository.delete_for_document",
        lambda filename, user_id: None,
    )

    assert service.delete_document("missing.txt", "local-dev") is True
    assert repository.deleted == [("missing.txt", "local-dev")]
