"""Retryable cleanup for derived data after a document tombstone is written."""

from __future__ import annotations

import logging
from typing import Any

from app.core.celery_app import celery_app
from app.core.config import settings
from app.services.document_service import document_service
from app.services.document_repository import document_repository

log = logging.getLogger(__name__)


def _run_document_cleanup_retry(
    self,
    *,
    document_id: str,
    user_id: str,
    workspace_id: str | None,
) -> dict[str, Any]:
    """Run the same idempotent cleanup body for both task names."""
    try:
        completed = document_service.run_deleted_document_cleanup(
            document_id,
            user_id=user_id,
            workspace_id=workspace_id,
        )
    except Exception as exc:
        retry = getattr(self, "retry", None)
        if retry is None:
            log.error(
                "Document cleanup retry is unavailable for document %s: %s",
                document_id,
                exc,
            )
            return {"document_id": document_id, "status": "failed"}
        attempt = int(getattr(getattr(self, "request", None), "retries", 0) or 0)
        retry_delay = max(
            1,
            int(getattr(settings, "CELERY_DOCUMENT_CLEANUP_RETRY_DELAY_SECONDS", 60)),
        )
        raise retry(exc=exc, countdown=min(300, retry_delay * (2**attempt)))
    return {
        "document_id": document_id,
        "status": "completed" if completed else "skipped",
    }


@celery_app.task(
    bind=True,
    name="app.tasks.document_cleanup.retry_document_cleanup",
    max_retries=5,
)
def retry_document_cleanup(
    self,
    document_id: str,
    user_id: str,
    workspace_id: str | None = None,
) -> dict[str, Any]:
    """Retry all already-scoped cleanup without resurrecting the document."""
    return _run_document_cleanup_retry(
        self,
        document_id=document_id,
        user_id=user_id,
        workspace_id=workspace_id,
    )


@celery_app.task(
    bind=True,
    name="app.tasks.document_cleanup.retry_visit_preparation_cleanup",
    max_retries=5,
)
def retry_visit_preparation_cleanup(
    self,
    document_id: str,
    user_id: str,
    workspace_id: str | None = None,
) -> dict[str, Any]:
    """Keep the old task name working while retrying the full cleanup."""
    return _run_document_cleanup_retry(
        self,
        document_id=document_id,
        user_id=user_id,
        workspace_id=workspace_id,
    )


@celery_app.task(
    name="app.tasks.document_cleanup.retry_pending_document_cleanups",
)
def retry_pending_document_cleanups(limit: int = 100) -> dict[str, Any]:
    """Publish due tombstones so broker outages are recoverable later."""
    candidates = document_repository.list_cleanup_candidates(limit=limit)
    queued = 0
    publish_failures = 0
    for candidate in candidates:
        try:
            retry_document_cleanup.apply_async(kwargs=candidate)
            queued += 1
        except Exception as exc:
            # Leave the durable pending/failed row untouched. A later beat run
            # can publish it after the broker becomes available again.
            publish_failures += 1
            log.error(
                "Could not publish cleanup for document %s: %s",
                candidate.get("document_id", ""),
                exc,
            )
    return {
        "status": "completed",
        "candidates": len(candidates),
        "queued": queued,
        "publish_failures": publish_failures,
    }
