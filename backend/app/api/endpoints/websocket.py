"""WebSocket progress stream for background jobs."""

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.api.endpoints.auth import _ensure_dev_user, _user_from_id
from app.core.config import settings
from app.services.job_repository import job_repository
from app.services.websocket_ticket import consume_job_ws_ticket

log = logging.getLogger(__name__)
router = APIRouter()


@router.websocket("/ws/jobs/{job_id}")
async def job_progress_ws(websocket: WebSocket, job_id: str):
    """Stream a job only after authenticating and checking its owner."""
    user = await _websocket_user(websocket, job_id)
    if user is None:
        await websocket.close(code=1008, reason="Authentication required")
        return

    stored = job_repository.get(job_id, user.id)
    if not stored:
        # A Celery id alone is not proof that the caller may see the task.
        await websocket.close(code=1008, reason="Job not found")
        return

    await websocket.accept()
    log.debug("WS connected for job %s", job_id)

    try:
        from app.core.celery_app import celery_app
        task = celery_app.AsyncResult(job_id)

        last_state: dict[str, Any] = {}

        while True:
            current = task_snapshot(task)

            # Keep the socket quiet while Celery is reporting the same state.
            if current != last_state:
                await websocket.send_text(json.dumps(current))
                last_state = current

            if current["state"] in ("SUCCESS", "FAILURE", "REVOKED"):
                break

            await asyncio.sleep(0.5)

    except WebSocketDisconnect:
        log.debug("WS client disconnected for job %s", job_id)
    except Exception as exc:
        log.error("WS error for job %s: %s", job_id, exc)
        try:
            await websocket.send_text(json.dumps({"state": "ERROR", "error": str(exc)}))
        except Exception:
            pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


async def _websocket_user(websocket: WebSocket, job_id: str):
    """Resolve the user from a one-use job ticket, not a reusable JWT."""
    ticket = websocket.query_params.get("ticket")
    if ticket:
        user_id = await consume_job_ws_ticket(ticket, job_id)
        return _user_from_id(user_id) if user_id else None
    if websocket.query_params.get("access_token"):
        # The old URL token is deliberately not supported anymore.
        return None
    if settings.AUTH_REQUIRED:
        return None
    return _ensure_dev_user()


def task_snapshot(task) -> dict[str, Any]:
    """Extract a serialisable snapshot from a Celery AsyncResult."""
    state = task.state

    if state == "PENDING":
        return {"state": "PENDING", "pct": 0, "step": "Waiting in queue…"}

    if state == "PROGRESS":
        info = task.info or {}
        return {
            "state": "PROGRESS",
            "pct":   info.get("pct", 0),
            "step":  info.get("step", "Processing…"),
        }

    if state == "SUCCESS":
        return {
            "state":  "SUCCESS",
            "pct":    100,
            "step":   "Done",
            "result": task.result if isinstance(task.result, dict) else {},
        }

    if state == "REVOKED":
        return {
            "state": "REVOKED",
            "pct":   0,
            "step":  "Cancelled",
            "error": "Cancelled",
        }

    if state == "FAILURE":
        return {
            "state": state,
            "pct":   0,
            "step":  "Failed",
            "error": str(task.info) if task.info else "Unknown error",
        }

    # STARTED or custom states
    return {"state": state, "pct": 0, "step": state.capitalize()}


class JobBroadcaster:
    """Small helper for the future case where several tabs watch the same job."""

    def __init__(self):
        self._subscribers: dict[str, set[WebSocket]] = {}

    def subscribe(self, job_id: str, ws: WebSocket):
        self._subscribers.setdefault(job_id, set()).add(ws)

    def unsubscribe(self, job_id: str, ws: WebSocket):
        subs = self._subscribers.get(job_id, set())
        subs.discard(ws)
        if not subs:
            self._subscribers.pop(job_id, None)

    async def broadcast(self, job_id: str, message: dict[str, Any]):
        """Send to all clients watching this job. Remove dead connections."""
        dead: set[WebSocket] = set()
        for ws in self._subscribers.get(job_id, set()):
            try:
                await ws.send_text(json.dumps(message))
            except Exception:
                dead.add(ws)
        for ws in dead:
            self.unsubscribe(job_id, ws)


broadcaster = JobBroadcaster()

_task_snapshot = task_snapshot
