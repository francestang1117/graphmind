"""Background entrypoint for parsing a stored document."""

import logging
from typing import Any, Dict

from app.core.celery_app import celery_app
from app.services.document_service import document_service
from app.services.pipeline import pipeline


log = logging.getLogger(__name__)


@celery_app.task(bind=True, name="app.tasks.process_document.process_document")
def process_document(self, file_path: str, filename: str = "") -> Dict[str, Any]:
    _progress(self, 5, "Queued document pipeline")
    return pipeline.process(
        file_path,
        filename or file_path.rsplit("/", 1)[-1],
        filename or "",
        on_progress=lambda step, pct: _progress(self, pct, step),
    )


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

    _progress(self, 5, "Queued document reindex")
    return pipeline.process(
        metadata["file_path"],
        metadata["filename"],
        metadata.get("original_filename", metadata["filename"]),
        on_progress=lambda step, pct: _progress(self, pct, step),
    )


@celery_app.task(bind=True, name="app.tasks.process_document.reindex_all_documents")
def reindex_all_documents(
    self,
    user_id: str | None = None,
) -> Dict[str, Any]:
    """Reindex current documents without letting one bad file stop the batch."""
    _progress(self, 5, "Listing documents for reindex")
    documents = document_service.list_documents(user_id)
    total = len(documents)
    results: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []

    for index, metadata in enumerate(documents, start=1):
        filename = metadata["filename"]
        original = metadata.get("original_filename", filename)
        # Keep the batch progress simple. A tiny text file and a PDF will not
        # take the same time, but this is enough for a maintenance task.
        pct = 5 + int((index - 1) / max(total, 1) * 90)
        _progress(self, pct, f"Reindexing {original}")
        try:
            results.append(
                pipeline.process(
                    metadata["file_path"],
                    filename,
                    original,
                )
            )
        except Exception as exc:
            # One bad file should not block the rest of the library refresh.
            # Return the filename so the failure is visible from task results.
            log.warning("Could not reindex %s: %s", original, exc)
            failures.append({"filename": filename, "error": str(exc)})

    _progress(self, 100, "Reindex complete")
    return {
        "status": "completed" if not failures else "completed_with_errors",
        "total": total,
        "reindexed": len(results),
        "failed": len(failures),
        "results": results,
        "failures": failures,
    }


def _progress(task, pct: int, step: str) -> None:
    """Best-effort progress update for Celery workers and the local fallback."""
    update_state = getattr(task, "update_state", None)
    if update_state:
        update_state(state="PROGRESS", meta={"pct": pct, "step": step})
