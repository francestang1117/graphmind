"""HTTP job helpers for task status and cancellation."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import router


class FakeTask:
    state = "PROGRESS"
    info = {"pct": 55, "step": "Indexing chunks"}
    result = {}


class FakeControl:
    def __init__(self):
        self.revoked = []

    def revoke(self, job_id, terminate=False):
        self.revoked.append((job_id, terminate))


class FakeCelery:
    def __init__(self):
        self.control = FakeControl()
        self.task = FakeTask()

    def AsyncResult(self, _job_id):
        return self.task


def _client(monkeypatch, fake):
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    monkeypatch.setattr("app.api.endpoints.jobs.celery_app", fake)
    return TestClient(app)


def test_get_job_returns_current_snapshot(monkeypatch):
    response = _client(monkeypatch, FakeCelery()).get("/api/v1/jobs/job-1")

    assert response.status_code == 200
    assert response.json() == {"state": "PROGRESS", "pct": 55, "step": "Indexing chunks"}


def test_cancel_job_revokes_task(monkeypatch):
    fake = FakeCelery()
    response = _client(monkeypatch, fake).post("/api/v1/jobs/job-1/cancel")

    assert response.status_code == 200
    assert fake.control.revoked == [("job-1", True)]
    assert response.json()["state"] == "REVOKED"
