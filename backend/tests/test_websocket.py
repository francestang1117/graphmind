"""WebSocket progress endpoint tests."""

import asyncio
import json

from app.api.endpoints.websocket import _task_snapshot, job_progress_ws


class FakeTask:
    def __init__(self, states):
        self._states = list(states)
        self.info = None
        self.result = None

    @property
    def state(self):
        state, info, result = self._states.pop(0) if self._states else self._last
        self._last = (state, info, result)
        self.info = info
        self.result = result
        return state


class FakeCelery:
    def __init__(self, task):
        self.task = task

    def AsyncResult(self, _job_id):
        return self.task


class FakeWebSocket:
    def __init__(self) -> None:
        self.accepted = False
        self.closed = False
        self.messages: list[dict] = []

    async def accept(self) -> None:
        self.accepted = True

    async def send_text(self, message: str) -> None:
        self.messages.append(json.loads(message))

    async def close(self) -> None:
        self.closed = True


def test_task_snapshot_formats_progress_and_success():
    progress = FakeTask([("PROGRESS", {"pct": 45, "step": "Parsing"}, None)])
    success = FakeTask([("SUCCESS", None, {"chunks": 3})])

    assert _task_snapshot(progress) == {"state": "PROGRESS", "pct": 45, "step": "Parsing"}
    assert _task_snapshot(success) == {
        "state": "SUCCESS",
        "pct": 100,
        "step": "Done",
        "result": {"chunks": 3},
    }


def test_job_progress_websocket_streams_until_success(monkeypatch):
    task = FakeTask(
        [
            ("PENDING", None, None),
            ("PROGRESS", {"pct": 35, "step": "Parsing document"}, None),
            ("SUCCESS", None, {"chunks": 2}),
        ]
    )
    monkeypatch.setattr("app.core.celery_app.celery_app", FakeCelery(task))
    websocket = FakeWebSocket()

    asyncio.run(job_progress_ws(websocket, "job-123"))

    assert websocket.accepted is True
    assert websocket.closed is True
    assert websocket.messages == [
        {"state": "PENDING", "pct": 0, "step": "Waiting in queue…"},
        {"state": "PROGRESS", "pct": 35, "step": "Parsing document"},
        {"state": "SUCCESS", "pct": 100, "step": "Done", "result": {"chunks": 2}},
    ]
