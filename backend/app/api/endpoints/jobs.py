"""HTTP access to background job state."""

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel

from app.api.endpoints.auth import UserRecord, current_user_or_dev
from app.api.endpoints.websocket import task_snapshot
from app.core.celery_app import celery_app
from app.services.job_repository import job_repository
from app.services.websocket_ticket import (
    JOB_WS_TICKET_TTL_SECONDS,
    WebSocketTicketStoreUnavailable,
    issue_job_ws_ticket,
)

router = APIRouter()


def _user_id(user: UserRecord) -> str:
    return getattr(user, "id", "local-dev")


class JobInfo(BaseModel):
    job_id: str
    workspace_id: str | None = None
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


class WebSocketTicketResponse(BaseModel):
    ticket: str
    expires_in: int


@router.get("/", response_model=JobListResponse)
async def list_jobs(
    limit: int = Query(default=50, ge=1, le=200),
    workspace_id: str | None = Query(None),
    user: UserRecord = Depends(current_user_or_dev),
) -> JobListResponse:
    """Return recent background jobs for the current user."""
    if workspace_id is None:
        rows = job_repository.list(_user_id(user), limit=limit)
    else:
        from app.api.workspace_scope import resolve_workspace_id

        scope = resolve_workspace_id(_user_id(user), workspace_id)
        rows = job_repository.list(_user_id(user), limit=limit, workspace_id=scope)
    jobs = [JobInfo(**item) for item in rows]
    return JobListResponse(jobs=jobs, total=len(jobs))


@router.post("/{job_id}/ws-ticket", response_model=WebSocketTicketResponse)
async def create_ws_ticket(
    job_id: str,
    response: Response,
    workspace_id: str | None = Query(None),
    user: UserRecord = Depends(current_user_or_dev),
) -> WebSocketTicketResponse:
    """Create the short-lived credential used by the job progress socket."""
    user_id = _user_id(user)
    stored = _get_job(job_id, user_id, workspace_id)
    if not stored:
        raise HTTPException(status_code=404, detail="Job not found")

    response.headers["Cache-Control"] = "no-store"
    try:
        ticket = await issue_job_ws_ticket(job_id, user_id)
    except WebSocketTicketStoreUnavailable as exc:
        # A ticket must be shared by the API and WebSocket instances.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="WebSocket progress is temporarily unavailable",
            headers={"Retry-After": "5"},
        ) from exc
    return WebSocketTicketResponse(
        ticket=ticket,
        expires_in=JOB_WS_TICKET_TTL_SECONDS,
    )


@router.get("/{job_id}")
async def get_job(
    job_id: str,
    workspace_id: str | None = Query(None),
    user: UserRecord = Depends(current_user_or_dev),
) -> dict:
    """Return the same snapshot the upload UI receives over WebSocket."""
    stored = _get_job(job_id, _user_id(user), workspace_id)
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
    workspace_id: str | None = Query(None),
    user: UserRecord = Depends(current_user_or_dev),
) -> dict:
    """Ask Celery to stop a queued or running task."""
    stored = _get_job(job_id, _user_id(user), workspace_id)
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
            workspace_id=stored.get("workspace_id"),
        )
        return {"state": "REVOKED", "pct": 0, "step": "Cancelled", "error": "Cancelled"}
    return snapshot


def _get_job(job_id: str, user_id: str, workspace_id: str | None = None):
    """Validate a workspace only when the caller explicitly selected one."""
    if workspace_id is None:
        return job_repository.get(job_id, user_id)

    from app.api.workspace_scope import resolve_workspace_id

    scope = resolve_workspace_id(user_id, workspace_id)
    return job_repository.get(job_id, user_id, scope)
