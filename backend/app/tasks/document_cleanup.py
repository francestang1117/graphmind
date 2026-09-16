"""Retryable cleanup for derived data after a document tombstone is written."""

from __future__ import annotations

import logging
from typing import Any

from app.core.celery_app import celery_app
from app.services.medical.visit_preparation.exceptions import VisitPreparationError
from app.services.medical.visit_preparation.repository import (
    visit_preparation_repository,
)

log = logging.getLogger(__name__)


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
    """Retry an already-scoped cleanup without resurrecting the document."""
    try:
        visit_preparation_repository.delete_for_document(
            document_id,
            user_id=user_id,
            workspace_id=workspace_id,
        )
    except VisitPreparationError as exc:
        retry = getattr(self, "retry", None)
        if retry is None:
            log.error(
                "Visit preparation cleanup retry is unavailable for document %s: %s",
                document_id,
                exc,
            )
            return {"document_id": document_id, "status": "failed"}
        attempt = int(getattr(getattr(self, "request", None), "retries", 0) or 0)
        raise retry(exc=exc, countdown=min(300, 5 * (2**attempt)))
    return {"document_id": document_id, "status": "completed"}
