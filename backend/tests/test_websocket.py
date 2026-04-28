"""WebSocket tests for the current placeholder progress endpoint."""

import asyncio

from app.api.endpoints.websocket import job_progress_ws


class FakeWebSocket:
    def __init__(self) -> None:
        self.accepted = False
        self.closed = False
        self.messages: list[dict] = []

    async def accept(self) -> None:
        self.accepted = True

    async def send_json(self, message: dict) -> None:
        self.messages.append(message)

    async def close(self) -> None:
        self.closed = True


def test_job_progress_websocket_sends_placeholder_message():
    websocket = FakeWebSocket()

    asyncio.run(job_progress_ws(websocket, "job-123"))

    assert websocket.accepted is True
    assert websocket.closed is True
    assert websocket.messages == [
        {
            "stage": "pending",
            "pct": 0,
            "detail": "Progress streaming for job-123 is not wired yet.",
        }
    ]
