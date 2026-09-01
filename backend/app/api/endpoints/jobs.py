"""HTTP access to background job state."""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.api.endpoints.auth import UserRecord, current_user_or_dev
from app.api.endpoints.websocket import task_snapshot
from app.core.celery_app import celery_app
from app.services.job_repository import job_repository

router = APIRouter()


def _user_id(user: UserRecord) -> str:
    return getattr(user, "id", "local-dev")


class JobInfo(BaseModel):
    job_id: str
    document_id: str = ""
    original_filename: str = ""
    status: str
    step: str
    progress: int
    error: str = ""
    created_at: str = ""
    updated_at: str = ""
    finished_at: str | None = None


class JobListResponse(BaseModel):
    jobs: list[JobInfo]
    total: int


@router.get("/", response_model=JobListResponse)
async def list_jobs(
    limit: int = Query(default=50, ge=1, le=200),
    user: UserRecord = Depends(current_user_or_dev),
) -> JobListResponse:
    """Return recent background jobs for the current user."""
    jobs = [JobInfo(**item) for item in job_repository.list(_user_id(user), limit=limit)]
    return JobListResponse(jobs=jobs, total=len(jobs))


@router.get("/{job_id}")
async def get_job(
    job_id: str,
    user: UserRecord = Depends(current_user_or_dev),
) -> dict:
    """Return the same snapshot the upload UI receives over WebSocket."""
    stored = job_repository.get(job_id, _user_id(user))
    if not stored:
        # Celery knows task ids, but it does not know which account owns them.
        # Do not let that global lookup become an access-control bypass.
        raise HTTPException(status_code=404, detail="Job not found")

    if stored and stored["status"] in {"SUCCESS", "FAILURE", "REVOKED", "ERROR"}:
        # Finished jobs can come straight from our history table. Celery result
        # backends may expire; the app's recent history is the steadier source.
        return {
            "state": stored["status"],
            "pct": stored["progress"],
            "step": stored["step"],
            "error": stored["error"] or None,
            "job": stored,
        }

    task = celery_app.AsyncResult(job_id)
    snapshot = task_snapshot(task)
    # Active jobs still use Celery for live state, with DB details attached for
    # filename/document context. The ownership check happened above.
    snapshot["job"] = stored
    return snapshot


@router.post("/{job_id}/cancel")
async def cancel_job(
    job_id: str,
    user: UserRecord = Depends(current_user_or_dev),
) -> dict:
    """Ask Celery to stop a queued or running task."""
    stored = job_repository.get(job_id, _user_id(user))
    if not stored:
        # Revoke is a global Celery operation, so it must never happen before
        # we know that this user owns the job id.
        raise HTTPException(status_code=404, detail="Job not found")

    celery_app.control.revoke(job_id, terminate=True)
    task = celery_app.AsyncResult(job_id)
    snapshot = task_snapshot(task)
    if snapshot["state"] in {"PENDING", "PROGRESS", "STARTED"}:
        # Celery can take a moment to report REVOKED. For the UI, the important
        # thing is that the user already cancelled it, so reflect that now.
        job_repository.upsert(
            job_id,
            user_id=_user_id(user),
            document_id=stored.get("document_id", ""),
            original_filename=stored.get("original_filename", ""),
            status="REVOKED",
            step="Cancelled",
            progress=0,
            error="Cancelled",
        )
        return {"state": "REVOKED", "pct": 0, "step": "Cancelled", "error": "Cancelled"}
    return snapshot
