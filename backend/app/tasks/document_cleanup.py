"""Retryable cleanup for derived data after a document tombstone is written."""

from __future__ import annotations

import logging
from typing import Any

from app.core.celery_app import celery_app
from app.services.document_service import document_service

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
        document_service.cleanup_deleted_document_data(
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
        raise retry(exc=exc, countdown=min(300, 5 * (2**attempt)))
    return {"document_id": document_id, "status": "completed"}


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
