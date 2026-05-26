"""HTTP access to background job state."""

from fastapi import APIRouter, Depends

from app.api.endpoints.auth import UserRecord, current_user_or_dev
from app.api.endpoints.websocket import task_snapshot
from app.core.celery_app import celery_app

router = APIRouter()


@router.get("/{job_id}")
async def get_job(
    job_id: str,
    _user: UserRecord = Depends(current_user_or_dev),
) -> dict:
    """Return the same snapshot the upload UI receives over WebSocket."""
    task = celery_app.AsyncResult(job_id)
    return task_snapshot(task)


@router.post("/{job_id}/cancel")
async def cancel_job(
    job_id: str,
    _user: UserRecord = Depends(current_user_or_dev),
) -> dict:
    """Ask Celery to stop a queued or running task."""
    celery_app.control.revoke(job_id, terminate=True)
    task = celery_app.AsyncResult(job_id)
    snapshot = task_snapshot(task)
    if snapshot["state"] in {"PENDING", "PROGRESS", "STARTED"}:
        # Celery can take a moment to report REVOKED. For the UI, the important
        # thing is that the user already cancelled it, so reflect that now.
        return {"state": "REVOKED", "pct": 0, "step": "Cancelled"}
    return snapshot
