"""WebSocket progress endpoint placeholder."""

from fastapi import APIRouter, WebSocket


router = APIRouter()


@router.websocket("/ws/jobs/{job_id}")
async def job_progress_ws(websocket: WebSocket, job_id: str) -> None:
    """Send a single development message until Redis progress exists."""
    await websocket.accept()
    await websocket.send_json(
        {
            "stage": "pending",
            "pct": 0,
            "detail": f"Progress streaming for {job_id} is not wired yet.",
        }
    )
    await websocket.close()
