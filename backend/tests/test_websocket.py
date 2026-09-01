"""WebSocket progress endpoint tests."""

import asyncio
import json

from app.api.endpoints import auth
from app.api.endpoints.websocket import _task_snapshot, job_progress_ws
from app.services.websocket_ticket import consume_job_ws_ticket, issue_job_ws_ticket


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
        self.query_params = {}

    async def accept(self) -> None:
        self.accepted = True

    async def send_text(self, message: str) -> None:
        self.messages.append(json.loads(message))

    async def close(self, *args, **kwargs) -> None:
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
    monkeypatch.setattr(
        "app.api.endpoints.websocket.job_repository",
        _FakeJobRepository("local-dev"),
    )
    async def no_redis():
        return None

    monkeypatch.setattr("app.services.websocket_ticket._redis_client", no_redis)
    auth._ensure_dev_user()
    websocket = FakeWebSocket()
    websocket.query_params = {
        "ticket": asyncio.run(issue_job_ws_ticket("job-123", "local-dev")),
    }

    asyncio.run(job_progress_ws(websocket, "job-123"))

    assert websocket.accepted is True
    assert websocket.closed is True
    assert websocket.messages == [
        {"state": "PENDING", "pct": 0, "step": "Waiting in queue…"},
        {"state": "PROGRESS", "pct": 35, "step": "Parsing document"},
        {"state": "SUCCESS", "pct": 100, "step": "Done", "result": {"chunks": 2}},
    ]


def test_job_progress_websocket_rejects_unknown_job(monkeypatch):
    monkeypatch.setattr(
        "app.api.endpoints.websocket.job_repository",
        _FakeJobRepository(None),
    )
    websocket = FakeWebSocket()

    asyncio.run(job_progress_ws(websocket, "missing-job"))

    assert websocket.accepted is False
    assert websocket.closed is True
    assert websocket.messages == []


def test_job_ticket_is_bound_to_job_and_consumed_once(monkeypatch):
    async def no_redis():
        return None

    monkeypatch.setattr("app.services.websocket_ticket._redis_client", no_redis)

    ticket = asyncio.run(issue_job_ws_ticket("job-123", "user-1"))

    assert asyncio.run(consume_job_ws_ticket(ticket, "other-job")) is None
    assert asyncio.run(consume_job_ws_ticket(ticket, "job-123")) == "user-1"
    assert asyncio.run(consume_job_ws_ticket(ticket, "job-123")) is None


def test_websocket_does_not_accept_access_token_query(monkeypatch):
    monkeypatch.setattr("app.api.endpoints.websocket.settings.AUTH_REQUIRED", True)
    websocket = FakeWebSocket()
    websocket.query_params = {"access_token": "reusable-jwt"}

    asyncio.run(job_progress_ws(websocket, "job-123"))

    assert websocket.accepted is False
    assert websocket.closed is True


class _FakeJobRepository:
    def __init__(self, owner):
        self.owner = owner

    def get(self, _job_id, user_id):
        if self.owner == user_id:
            return {"job_id": "job-123", "user_id": user_id}
        return None
