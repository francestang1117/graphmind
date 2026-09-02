"""Background entrypoint for parsing a stored document."""

import logging
from typing import Any, Dict

from app.core.celery_app import celery_app
from app.core.config import settings
from app.services.document_service import document_service
from app.services.job_repository import job_repository
from app.services.pipeline import ProcessingCancelledError, pipeline


log = logging.getLogger(__name__)


@celery_app.task(bind=True, name="app.tasks.process_document.process_document")
def process_document(
    self,
    file_path: str,
    document_id: str = "",
    original_filename: str = "",
    user_id: str = "",
    stored_filename: str = "",
) -> Dict[str, Any]:
    stable_document_id = document_id or file_path.rsplit("/", 1)[-1]
    stored_name = stored_filename or document_id or file_path.rsplit("/", 1)[-1]
    display_name = original_filename or stored_name or ""
    owner_id = user_id or "local-dev"
    # The API creates the job row before publishing the task. That row carries
    # the workspace even when this task is still using the old five arguments.
    workspace_id = _job_workspace(self, owner_id) or _document_workspace(
        owner_id, stable_document_id, stored_name
    )
    try:
        # The upload route creates the first row, but the worker owns the live
        # status from here on.
        _progress(
            self,
            5,
            "Queued document pipeline",
            owner_id,
            stable_document_id,
            display_name,
            workspace_id=workspace_id,
        )
        result = pipeline.process(
            file_path,
            stored_name,
            display_name,
            user_id=owner_id,
            document_id=stable_document_id,
            on_progress=lambda step, pct: _progress(
                self,
                pct,
                step,
                owner_id,
                stable_document_id,
                display_name,
                workspace_id=workspace_id,
            ),
            should_cancel=lambda: _job_revoked(self, owner_id, workspace_id),
            workspace_id=workspace_id,
        )
        _progress(
            self,
            100,
            "Done",
            owner_id,
            stable_document_id,
            display_name,
            status="SUCCESS",
            workspace_id=workspace_id,
        )
        return result
    except ProcessingCancelledError:
        log.info("Skipping the rest of deleted document job %s", getattr(self.request, "id", ""))
        _set_revoked_state(self)
        return {
            "filename": stored_name,
            "document_id": stable_document_id,
            "status": "cancelled",
        }
    except Exception as exc:
        _progress(
            self,
            100,
            "Failed",
            owner_id,
            stable_document_id,
            display_name,
            status="FAILURE",
            error=str(exc),
            workspace_id=workspace_id,
        )
        raise


@celery_app.task(bind=True, name="app.tasks.process_document.reindex_document")
def reindex_document(
    self,
    filename: str,
    user_id: str | None = None,
    workspace_id: str | None = None,
) -> Dict[str, Any]:
    """Re-run the processing pipeline for one stored document."""
    # Reindex starts from saved metadata because the public filename is usually
    # a content hash, not a path a worker can guess on its own.
    metadata = (
        document_service.get_document(filename, user_id, workspace_id)
        if workspace_id is not None
        else document_service.get_document(filename, user_id)
    )
    if not metadata:
        log.warning("Could not reindex missing document %s", filename)
        return {"filename": filename, "status": "not_found"}

    owner_id = user_id or metadata.get("user_id", "local-dev")
    workspace_id = workspace_id or metadata.get("workspace_id")
    stable_document_id = metadata.get("document_id") or metadata["filename"]
    stored_filename = metadata.get("stored_filename") or metadata["filename"]
    try:
        _progress(
            self,
            5,
            "Queued document reindex",
            owner_id,
            stable_document_id,
            metadata.get("original_filename", stored_filename),
            workspace_id=workspace_id,
        )
        pipeline_kwargs = {
            "user_id": owner_id,
            "document_id": stable_document_id,
            "on_progress": lambda step, pct: _progress(
                self,
                pct,
                step,
                owner_id,
                stable_document_id,
                metadata.get("original_filename", stored_filename),
                workspace_id=workspace_id,
            ),
            "should_cancel": lambda: _job_revoked(self, owner_id, workspace_id),
        }
        if workspace_id is not None:
            pipeline_kwargs["workspace_id"] = workspace_id
        result = pipeline.process(
            metadata["file_path"],
            stored_filename,
            metadata.get("original_filename", metadata["filename"]),
            **pipeline_kwargs,
        )
        _progress(
            self,
            100,
            "Done",
            owner_id,
            stable_document_id,
            metadata.get("original_filename", stored_filename),
            status="SUCCESS",
            workspace_id=workspace_id,
        )
        return result
    except ProcessingCancelledError:
        log.info("Skipping the rest of deleted document reindex job %s", getattr(self.request, "id", ""))
        _set_revoked_state(self)
        return {
            "filename": stored_filename,
            "document_id": stable_document_id,
            "status": "cancelled",
        }
    except Exception as exc:
        _progress(
            self,
            100,
            "Failed",
            owner_id,
            stable_document_id,
            metadata.get("original_filename", stored_filename),
            status="FAILURE",
            error=str(exc),
            workspace_id=workspace_id,
        )
        raise


@celery_app.task(bind=True, name="app.tasks.process_document.reindex_all_documents")
def reindex_all_documents(
    self,
    user_id: str | None = None,
    workspace_id: str | None = None,
) -> Dict[str, Any]:
    """Reindex current documents without letting one bad file stop the batch."""
    _progress(
        self,
        5,
        "Listing documents for reindex",
        user_id or "",
        "",
        "Reindex all",
        workspace_id=workspace_id,
    )
    documents = (
        document_service.list_documents(user_id, workspace_id)
        if workspace_id is not None
        else document_service.list_documents(user_id)
    )
    total = len(documents)
    results: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []

    for index, metadata in enumerate(documents, start=1):
        filename = metadata["filename"]
        original = metadata.get("original_filename", filename)
        owner_id = user_id or metadata.get("user_id", "local-dev")
        document_workspace_id = workspace_id or metadata.get("workspace_id")
        stable_document_id = metadata.get("document_id") or filename
        stored_filename = metadata.get("stored_filename") or filename
        # Batch progress is file-count based. It is rough, but it keeps the
        # maintenance task readable without pretending we know each file's cost.
        pct = 5 + int((index - 1) / max(total, 1) * 90)
        _progress(
            self,
            pct,
            f"Reindexing {original}",
            owner_id,
            stable_document_id,
            original,
            workspace_id=document_workspace_id,
        )
        try:
            pipeline_kwargs = {
                "user_id": owner_id,
                "document_id": stable_document_id,
                "should_cancel": lambda: not _document_is_available(
                    document_service,
                    filename,
                    owner_id,
                    document_workspace_id,
                ),
            }
            if document_workspace_id is not None:
                pipeline_kwargs["workspace_id"] = document_workspace_id
            results.append(
                pipeline.process(
                    metadata["file_path"],
                    stored_filename,
                    original,
                    **pipeline_kwargs,
                )
            )
        except Exception as exc:
            # One bad file should not block the rest of the library refresh.
            # Return the filename so the failure is visible from task results.
            log.warning("Could not reindex %s: %s", original, exc)
            failures.append({"filename": filename, "error": str(exc)})

    _progress(
        self,
        100,
        "Reindex complete",
        user_id or "",
        "",
        "Reindex all",
        status="SUCCESS",
        workspace_id=workspace_id,
    )
    return {
        "status": "completed" if not failures else "completed_with_errors",
        "total": total,
        "reindexed": len(results),
        "failed": len(failures),
        "results": results,
        "failures": failures,
    }


@celery_app.task(bind=True, name="app.tasks.process_document.cleanup_finished_jobs")
def cleanup_finished_jobs(self) -> Dict[str, Any]:
    """Delete old finished job rows from the lightweight job history."""
    _progress(self, 10, "Cleaning old job history", "", "", "Job cleanup")
    removed = job_repository.cleanup_finished(settings.JOB_HISTORY_RETENTION_DAYS)
    _progress(self, 100, "Job cleanup complete", "", "", "Job cleanup", status="SUCCESS")
    return {"status": "completed", "removed": removed}


def _progress(
    task,
    pct: int,
    step: str,
    user_id: str = "",
    document_id: str = "",
    original_filename: str = "",
    *,
    status: str = "PROGRESS",
    error: str = "",
    workspace_id: str | None = None,
) -> None:
    """Best-effort progress update for Celery workers and the local fallback."""
    update_state = getattr(task, "update_state", None)
    job_id = ""
    request = getattr(task, "request", None)
    if request is not None:
        job_id = getattr(request, "id", "") or ""

    if job_id:
        if _job_revoked(task, user_id, workspace_id):
            raise ProcessingCancelledError("Document job was revoked")
        # Keep our DB copy close to Celery's state. The WebSocket is live-only;
        # this row is what survives refreshes and result-backend expiry.
        job_repository.upsert(
            job_id,
            user_id=user_id,
            document_id=document_id,
            original_filename=original_filename,
            status=status,
            step=step,
            progress=pct,
            error=error,
            workspace_id=workspace_id,
        )

    if update_state:
        if request is not None and getattr(request, "id", None) is None:
            return
        # Celery's result backend feeds the WebSocket path.
        update_state(state=status, meta={"pct": pct, "step": step, "error": error})


def _job_was_revoked(task, user_id: str, workspace_id: str | None = None) -> bool:
    """Read the database tombstone between worker stages."""
    request = getattr(task, "request", None)
    job_id = getattr(request, "id", "") if request is not None else ""
    checker = getattr(job_repository, "is_revoked", None)
    if not job_id or not checker:
        return False
    if workspace_id is None:
        return bool(checker(job_id, user_id))
    return bool(checker(job_id, user_id, workspace_id))


def _job_revoked(task, user_id: str, workspace_id: str | None = None) -> bool:
    """Keep the old two-argument task hook working for local tests/workers."""
    if workspace_id is None:
        return _job_was_revoked(task, user_id)
    return _job_was_revoked(task, user_id, workspace_id)


def _document_workspace(owner_id: str, document_id: str, stored_name: str) -> str | None:
    """Load the scope once; task arguments stay compatible with old workers."""
    try:
        metadata = document_service.get_document_by_id(document_id, owner_id)
        if not metadata and stored_name:
            metadata = document_service.get_document(stored_name, owner_id)
        return metadata.get("workspace_id") if metadata else None
    except Exception as exc:
        log.warning("Could not resolve workspace for document job %s: %s", document_id, exc)
        return None


def _job_workspace(task, user_id: str) -> str | None:
    """Read the workspace from the job created before the task was queued."""
    request = getattr(task, "request", None)
    job_id = getattr(request, "id", "") if request is not None else ""
    lookup = getattr(job_repository, "get_for_owner", None)
    if not job_id or not lookup:
        return None

    try:
        job = lookup(job_id, user_id)
        return job.get("workspace_id") if job else None
    except Exception as exc:
        log.warning("Could not resolve workspace for job %s: %s", job_id, exc)
        return None


def _document_is_available(service, filename: str, user_id: str, workspace_id: str | None) -> bool:
    try:
        metadata = (
            service.get_document(filename, user_id, workspace_id)
            if workspace_id is not None
            else service.get_document(filename, user_id)
        )
        return bool(metadata)
    except Exception as exc:
        log.warning("Could not check document before reindex step: %s", exc)
        return False


def _set_revoked_state(task) -> None:
    """Keep Celery's live result in step with the persisted cancellation."""
    update_state = getattr(task, "update_state", None)
    request = getattr(task, "request", None)
    if not update_state or (request is not None and not getattr(request, "id", None)):
        return
    update_state(state="REVOKED", meta={"pct": 0, "step": "Cancelled", "error": "Document deleted"})
