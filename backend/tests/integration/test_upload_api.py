"""Endpoint-level checks for the current document upload workflow."""

import asyncio
from io import BytesIO
from pathlib import Path

from fastapi import BackgroundTasks, UploadFile
import pytest

from app.api.endpoints import documents
from app.core.errors import DuplicateUploadError, ProcessingQueueError, UploadRejectedError
from app.services.document_service import DocumentService
from app.services.file_storage import FileStorage


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def temp_document_service(tmp_path, monkeypatch):
    service = DocumentService(storage=FileStorage(tmp_path))
    monkeypatch.setattr(documents, "document_service", service)
    return service


def make_upload(filename, content):
    return UploadFile(filename=filename, file=BytesIO(content))


def test_upload_returns_stored_file_metadata(temp_document_service):
    response = run(
        documents.upload_document(
            BackgroundTasks(),
            make_upload("notes.md", b"# Notes\n\nUseful text."),
        )
    )

    assert response.original_filename == "notes.md"
    assert response.status == "uploaded"
    assert response.file_type == ".md"
    assert response.job_id is None


def test_upload_can_queue_celery_job(temp_document_service, monkeypatch):
    queued = {}

    class FakeAsyncResult:
        def __init__(self, job_id):
            self.id = job_id

    class FakeTask:
        def apply_async(self, args, task_id):
            (
                queued["file_path"],
                queued["document_id"],
                queued["original_filename"],
                queued["user_id"],
                queued["stored_filename"],
            ) = args
            queued["task_id"] = task_id
            return FakeAsyncResult(task_id)

    class FakeJobRepository:
        def __init__(self):
            self.created = []

        def create(self, job_id, **kwargs):
            self.created.append((job_id, kwargs))

    monkeypatch.setattr(documents.settings, "CELERY_ENABLED", True)
    monkeypatch.setattr(documents, "process_document", FakeTask())
    fake_jobs = FakeJobRepository()
    monkeypatch.setattr(documents, "job_repository", fake_jobs)

    response = run(
        documents.upload_document(
            BackgroundTasks(),
            make_upload("notes.md", b"# Notes\n\nUseful text."),
        )
    )

    assert response.job_id
    assert queued["task_id"] == response.job_id
    assert queued["document_id"] == response.filename
    assert queued["stored_filename"] == response.filename
    assert queued["original_filename"] == "notes.md"
    assert queued["user_id"] == "local-dev"
    assert fake_jobs.created[0][0] == response.job_id


def test_fast_worker_completion_is_not_overwritten(temp_document_service, monkeypatch):
    events = []

    class FakeJobRepository:
        def __init__(self):
            self.rows = {}

        def create(self, job_id, **kwargs):
            events.append(("create", job_id))
            self.rows[job_id] = {"status": "PENDING", **kwargs}

        def upsert(self, job_id, **kwargs):
            events.append(("update", kwargs["status"]))
            self.rows[job_id].update(kwargs)

    fake_jobs = FakeJobRepository()

    class FakeTask:
        def apply_async(self, args, task_id):
            events.append(("publish", task_id))
            # Simulate a worker that finishes before apply_async returns.
            fake_jobs.upsert(
                task_id,
                user_id=args[3],
                document_id=args[1],
                original_filename=args[2],
                status="SUCCESS",
                step="Done",
                progress=100,
            )
            return object()

    monkeypatch.setattr(documents.settings, "CELERY_ENABLED", True)
    monkeypatch.setattr(documents, "process_document", FakeTask())
    monkeypatch.setattr(documents, "job_repository", fake_jobs)

    response = run(
        documents.upload_document(
            BackgroundTasks(),
            make_upload("fast.md", b"# Fast\n\nWorker finished quickly."),
        )
    )

    assert response.job_id
    assert events[0] == ("create", response.job_id)
    assert events[1] == ("publish", response.job_id)
    assert fake_jobs.rows[response.job_id]["status"] == "SUCCESS"
    assert fake_jobs.rows[response.job_id]["progress"] == 100


def test_queue_failure_is_saved_as_failed_job(temp_document_service, monkeypatch):
    class FakeJobRepository:
        def __init__(self):
            self.rows = {}

        def create(self, job_id, **kwargs):
            self.rows[job_id] = {"status": "PENDING", **kwargs}

        def upsert(self, job_id, **kwargs):
            self.rows[job_id].update(kwargs)

    class FailingTask:
        def apply_async(self, args, task_id):
            raise ConnectionError("broker is unavailable")

    fake_jobs = FakeJobRepository()
    monkeypatch.setattr(documents.settings, "CELERY_ENABLED", True)
    monkeypatch.setattr(documents, "process_document", FailingTask())
    monkeypatch.setattr(documents, "job_repository", fake_jobs)

    with pytest.raises(ProcessingQueueError) as exc:
        run(
            documents.upload_document(
                BackgroundTasks(),
                make_upload("queue-failure.md", b"# Queue failure"),
            )
        )

    job_id = exc.value.details["job_id"]
    assert fake_jobs.rows[job_id]["status"] == "FAILURE"
    assert fake_jobs.rows[job_id]["step"] == "Queue failed"


def test_list_get_and_delete_document(temp_document_service):
    uploaded = run(
        documents.upload_document(
            BackgroundTasks(),
            make_upload("keep.txt", b"plain text"),
        )
    )

    listed = run(documents.list_documents())
    fetched = run(documents.get_document(uploaded.filename))
    deleted = run(documents.delete_document(uploaded.filename))

    assert listed.total == 1
    assert fetched.original_filename == "keep.txt"
    assert deleted == {"message": "File deleted"}


def test_open_document_returns_original_file(temp_document_service):
    uploaded = run(
        documents.upload_document(
            BackgroundTasks(),
            make_upload("keep.txt", b"plain text"),
        )
    )

    response = run(documents.open_document(uploaded.filename))

    assert response.media_type == "text/plain"
    assert response.filename == "keep.txt"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-security-policy"] == "sandbox"
    assert response.headers["content-disposition"].startswith("inline")
    assert Path(response.path).read_bytes() == b"plain text"


def test_open_risky_document_downloads_instead_of_inline(temp_document_service):
    uploaded = run(
        documents.upload_document(
            BackgroundTasks(),
            make_upload("page.html", b"<!doctype html><script>alert(1)</script>"),
        )
    )

    response = run(documents.open_document(uploaded.filename))

    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-disposition"].startswith("attachment")


def test_open_missing_document_raises_not_found(temp_document_service):
    with pytest.raises(documents.HTTPException) as exc:
        run(documents.open_document("missing.txt"))

    assert exc.value.status_code == 404


def test_parsed_document_persists_chunks_and_entities(temp_document_service, monkeypatch):
    saved = {}

    class FakeArtifactRepository:
        def replace_for_document(self, filename, parsed, entities, *, user_id="local-dev"):
            saved["filename"] = filename
            saved["user_id"] = user_id
            saved["chunks"] = parsed.get("chunks", [])
            saved["entities"] = entities

        def delete_for_document(self, filename, *, user_id="local-dev"):
            saved["deleted"] = filename

    monkeypatch.setattr(
        "app.api.endpoints.documents_with_markdown.parsed_artifact_repository",
        FakeArtifactRepository(),
    )

    uploaded = run(
        documents.upload_document(
            BackgroundTasks(),
            make_upload("notes.md", b"# Notes\n\nGraphMind uses FastAPI and Python."),
        )
    )

    parsed = run(documents.get_parsed_document(uploaded.filename))

    assert parsed.chunks_count > 0
    assert saved["filename"] == uploaded.filename
    assert saved["chunks"]
    assert any(getattr(entity, "text", "") == "FastAPI" for entity in saved["entities"])


def test_invalid_upload_raises_http_error(temp_document_service):
    with pytest.raises(UploadRejectedError) as exc:
        run(
            documents.upload_document(
                BackgroundTasks(),
                make_upload("bad.exe", b"MZ"),
            )
        )

    assert exc.value.status_code == 400
    assert exc.value.code == "upload_validation_failed"


def test_duplicate_upload_has_stable_error_code(temp_document_service):
    run(
        documents.upload_document(
            BackgroundTasks(),
            make_upload("notes.md", b"# Notes"),
        )
    )

    with pytest.raises(DuplicateUploadError) as exc:
        run(
            documents.upload_document(
                BackgroundTasks(),
                make_upload("copy.md", b"# Notes"),
            )
        )

    assert exc.value.status_code == 409
    assert exc.value.code == "duplicate_file"
    assert exc.value.details["original_filename"] == "notes.md"
