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
    try:
        # The upload route creates the first row, but the worker owns the live
        # status from here on.
        _progress(self, 5, "Queued document pipeline", owner_id, stable_document_id, display_name)
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
            ),
            should_cancel=lambda: _job_was_revoked(self, owner_id),
        )
        _progress(self, 100, "Done", owner_id, stable_document_id, display_name, status="SUCCESS")
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
        )
        raise


@celery_app.task(bind=True, name="app.tasks.process_document.reindex_document")
def reindex_document(
    self,
    filename: str,
    user_id: str | None = None,
) -> Dict[str, Any]:
    """Re-run the processing pipeline for one stored document."""
    # Reindex starts from saved metadata because the public filename is usually
    # a content hash, not a path a worker can guess on its own.
    metadata = document_service.get_document(filename, user_id)
    if not metadata:
        log.warning("Could not reindex missing document %s", filename)
        return {"filename": filename, "status": "not_found"}

    owner_id = user_id or metadata.get("user_id", "local-dev")
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
        )
        result = pipeline.process(
            metadata["file_path"],
            stored_filename,
            metadata.get("original_filename", metadata["filename"]),
            user_id=owner_id,
            document_id=stable_document_id,
            on_progress=lambda step, pct: _progress(
                self,
                pct,
                step,
                owner_id,
                stable_document_id,
                metadata.get("original_filename", stored_filename),
            ),
            should_cancel=lambda: _job_was_revoked(self, owner_id),
        )
        _progress(
            self,
            100,
            "Done",
            owner_id,
            stable_document_id,
            metadata.get("original_filename", stored_filename),
            status="SUCCESS",
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
        )
        raise


@celery_app.task(bind=True, name="app.tasks.process_document.reindex_all_documents")
def reindex_all_documents(
    self,
    user_id: str | None = None,
) -> Dict[str, Any]:
    """Reindex current documents without letting one bad file stop the batch."""
    _progress(self, 5, "Listing documents for reindex", user_id or "", "", "Reindex all")
    documents = document_service.list_documents(user_id)
    total = len(documents)
    results: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []

    for index, metadata in enumerate(documents, start=1):
        filename = metadata["filename"]
        original = metadata.get("original_filename", filename)
        owner_id = user_id or metadata.get("user_id", "local-dev")
        stable_document_id = metadata.get("document_id") or filename
        stored_filename = metadata.get("stored_filename") or filename
        # Batch progress is file-count based. It is rough, but it keeps the
        # maintenance task readable without pretending we know each file's cost.
        pct = 5 + int((index - 1) / max(total, 1) * 90)
        _progress(self, pct, f"Reindexing {original}", owner_id, stable_document_id, original)
        try:
            results.append(
                pipeline.process(
                    metadata["file_path"],
                    stored_filename,
                    original,
                    user_id=owner_id,
                    document_id=stable_document_id,
                    should_cancel=lambda: not document_service.get_document(filename, owner_id),
                )
            )
        except Exception as exc:
            # One bad file should not block the rest of the library refresh.
            # Return the filename so the failure is visible from task results.
            log.warning("Could not reindex %s: %s", original, exc)
            failures.append({"filename": filename, "error": str(exc)})

    _progress(self, 100, "Reindex complete", user_id or "", "", "Reindex all", status="SUCCESS")
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
) -> None:
    """Best-effort progress update for Celery workers and the local fallback."""
    update_state = getattr(task, "update_state", None)
    job_id = ""
    request = getattr(task, "request", None)
    if request is not None:
        job_id = getattr(request, "id", "") or ""

    if job_id:
        if _job_was_revoked(task, user_id):
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
        )

    if update_state:
        if request is not None and getattr(request, "id", None) is None:
            return
        # Celery's result backend feeds the WebSocket path.
        update_state(state=status, meta={"pct": pct, "step": step, "error": error})


def _job_was_revoked(task, user_id: str) -> bool:
    """Read the database tombstone between worker stages."""
    request = getattr(task, "request", None)
    job_id = getattr(request, "id", "") if request is not None else ""
    checker = getattr(job_repository, "is_revoked", None)
    return bool(job_id and checker and checker(job_id, user_id))


def _set_revoked_state(task) -> None:
    """Keep Celery's live result in step with the persisted cancellation."""
    update_state = getattr(task, "update_state", None)
    request = getattr(task, "request", None)
    if not update_state or (request is not None and not getattr(request, "id", None)):
        return
    update_state(state="REVOKED", meta={"pct": 0, "step": "Cancelled", "error": "Document deleted"})
