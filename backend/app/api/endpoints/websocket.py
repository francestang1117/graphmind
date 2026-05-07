"""WebSocket progress stream for background jobs."""

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

log = logging.getLogger(__name__)
router = APIRouter()


@router.websocket("/ws/jobs/{job_id}")
async def job_progress_ws(websocket: WebSocket, job_id: str):
    """Stream Celery task progress to the browser."""
    await websocket.accept()
    log.debug("WS connected for job %s", job_id)

    try:
        from app.core.celery_app import celery_app
        task = celery_app.AsyncResult(job_id)

        last_state: dict[str, Any] = {}

        while True:
            current = _task_snapshot(task)

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


def _task_snapshot(task) -> dict[str, Any]:
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

    if state in ("FAILURE", "REVOKED"):
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
