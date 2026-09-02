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


class EmptyJobRepository:
    def list_for_document(self, document_id, user_id):
        return []


class ActiveDocumentRepository(StaleDocumentRepository):
    def get(self, filename, user_id):
        return {
            "document_id": "doc-1",
            "filename": filename,
            "user_id": user_id,
            "original_filename": filename,
        }


class ActiveJobRepository:
    def __init__(self):
        self.updates = []

    def list_for_document(self, document_id, user_id):
        return [{
            "job_id": "job-1",
            "original_filename": "notes.md",
        }]

    def upsert(self, job_id, **values):
        self.updates.append((job_id, values))


class FakeCeleryControl:
    def __init__(self):
        self.revoked = []

    def revoke(self, job_id, terminate=False):
        self.revoked.append((job_id, terminate))


class FakeCelery:
    def __init__(self):
        self.control = FakeCeleryControl()


def test_delete_soft_deletes_stale_database_record(monkeypatch):
    repository = StaleDocumentRepository()
    service = DocumentService(
        storage=MissingFileStorage(),
        repository=repository,
        use_database=True,
        virus_scan_enabled=False,
        job_repo=EmptyJobRepository(),
    )
    monkeypatch.setattr(
        "app.services.parsed_artifact_repository.parsed_artifact_repository.delete_for_document",
        lambda filename, *, user_id="local-dev": None,
    )
    monkeypatch.setattr(
        "app.services.graph_repository.graph_repository.delete_for_document",
        lambda filename, user_id: None,
    )

    assert service.delete_document("missing.txt", "local-dev") is True
    assert repository.deleted == [("missing.txt", "local-dev")]


def test_delete_marks_active_jobs_revoked_before_revoke(monkeypatch):
    jobs = ActiveJobRepository()
    celery = FakeCelery()
    service = DocumentService(
        storage=MissingFileStorage(),
        repository=ActiveDocumentRepository(),
        use_database=True,
        virus_scan_enabled=False,
        job_repo=jobs,
    )
    monkeypatch.setattr("app.core.celery_app.celery_app", celery)
    monkeypatch.setattr(
        "app.services.parsed_artifact_repository.parsed_artifact_repository.delete_for_document",
        lambda filename, *, user_id="local-dev": None,
    )
    monkeypatch.setattr(
        "app.services.graph_repository.graph_repository.delete_for_document",
        lambda filename, user_id: None,
    )

    assert service.delete_document("notes.md", "u1") is True
    assert jobs.updates == [
        (
            "job-1",
            {
                "user_id": "u1",
                "document_id": "doc-1",
                "original_filename": "notes.md",
                "status": "REVOKED",
                "step": "Cancelled: document deleted",
                "progress": 0,
                "error": "Document deleted",
            },
        )
    ]
    assert celery.control.revoked == [("job-1", True)]
