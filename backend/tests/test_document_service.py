"""Document service behavior that spans metadata and file storage."""

import pytest

from app.core.errors import DocumentCleanupError
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


class TrackingCleanupRepository(ActiveDocumentRepository):
    def __init__(self):
        super().__init__()
        self.failed = []
        self.events = []

    def claim_cleanup(self, *_args, **_kwargs):
        return True

    def mark_cleanup_completed(self, *_args, **_kwargs):
        return None

    def mark_cleanup_failed(self, *args, **kwargs):
        self.events.append("state")
        self.failed.append((args, kwargs))


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


def test_delete_does_not_report_success_when_visit_cleanup_fails(monkeypatch):
    service = DocumentService(
        storage=MissingFileStorage(),
        repository=ActiveDocumentRepository(),
        use_database=True,
        virus_scan_enabled=False,
        job_repo=EmptyJobRepository(),
    )
    cleanup_calls = []

    for path in (
        "app.services.parsed_artifact_repository.parsed_artifact_repository.delete_for_document",
        "app.services.graph_repository.graph_repository.delete_for_document",
        "app.services.medical.repository.medical_repository.delete_for_document",
        "app.services.medical.ai.analysis_repository.medical_analysis_repository.delete_for_document",
        "app.services.medical.evidence_matching.repository.evidence_matching_repository.delete_for_document",
    ):
        monkeypatch.setattr(path, lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "app.services.medical.literature.repository.literature_repository.delete_for_document",
        lambda *args, **kwargs: cleanup_calls.append("literature"),
    )

    def fail_cleanup(*_args, **_kwargs):
        from app.services.medical.visit_preparation.exceptions import VisitPreparationError

        cleanup_calls.append("visit_preparation")
        raise VisitPreparationError(
            "simulated cleanup failure",
            code="visit_preparation_cleanup_failed",
        )

    monkeypatch.setattr(
        "app.services.medical.visit_preparation.repository.visit_preparation_repository.delete_for_document",
        fail_cleanup,
    )
    monkeypatch.setattr(
        service,
        "_schedule_document_cleanup",
        lambda *args, **kwargs: None,
    )

    with pytest.raises(DocumentCleanupError) as exc:
        service.delete_document("notes.md", "u1")

    assert exc.value.code == "document_cleanup_incomplete"
    assert cleanup_calls == ["literature", "visit_preparation"]


def test_cleanup_failure_is_recorded_before_broker_publish(monkeypatch):
    repository = TrackingCleanupRepository()
    service = DocumentService(
        storage=MissingFileStorage(),
        repository=repository,
        use_database=True,
        virus_scan_enabled=False,
        job_repo=EmptyJobRepository(),
    )

    def fail_cleanup(*_args, **_kwargs):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(service, "cleanup_deleted_document_data", fail_cleanup)
    monkeypatch.setattr("app.services.document_service.settings.CELERY_ENABLED", True)

    def fail_publish(**_kwargs):
        repository.events.append("publish")
        raise RuntimeError("broker unavailable")

    monkeypatch.setattr(
        "app.tasks.document_cleanup.retry_document_cleanup.apply_async",
        fail_publish,
    )

    with pytest.raises(DocumentCleanupError):
        service._cleanup_deleted_document_data(
            "doc-1",
            user_id="u1",
            workspace_id="workspace-1",
        )

    assert len(repository.failed) == 1
    assert repository.failed[0][0] == ("doc-1", "u1", "workspace-1")
    assert repository.failed[0][1]["error_code"] == "RuntimeError"
    assert repository.events == ["state", "publish"]
