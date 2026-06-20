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


class FakeJobRepository:
    def __init__(self, row=None):
        self.row = row
        self.upserts = []

    def list(self, _user_id, limit=50):
        return [self.row] if self.row else []

    def get(self, _job_id, _user_id):
        return self.row

    def upsert(self, job_id, **kwargs):
        self.upserts.append((job_id, kwargs))


def _client(monkeypatch, fake):
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    monkeypatch.setattr("app.api.endpoints.jobs.celery_app", fake)
    monkeypatch.setattr("app.api.endpoints.jobs.job_repository", FakeJobRepository())
    return TestClient(app)


def test_get_job_returns_current_snapshot(monkeypatch):
    response = _client(monkeypatch, FakeCelery()).get("/api/v1/jobs/job-1")

    assert response.status_code == 200
    assert response.json() == {"state": "PROGRESS", "pct": 55, "step": "Indexing chunks"}


def test_cancel_job_revokes_task(monkeypatch):
    fake = FakeCelery()
    jobs = FakeJobRepository({
        "job_id": "job-1",
        "document_id": "hash.md",
        "original_filename": "notes.md",
        "status": "PROGRESS",
        "step": "Indexing chunks",
        "progress": 55,
        "error": "",
        "created_at": "",
        "updated_at": "",
        "finished_at": None,
    })
    client = _client(monkeypatch, fake)
    monkeypatch.setattr("app.api.endpoints.jobs.job_repository", jobs)

    response = client.post("/api/v1/jobs/job-1/cancel")

    assert response.status_code == 200
    assert fake.control.revoked == [("job-1", True)]
    assert response.json()["state"] == "REVOKED"
    assert jobs.upserts[0][1]["status"] == "REVOKED"


def test_list_jobs_returns_history(monkeypatch):
    row = {
        "job_id": "job-1",
        "document_id": "hash.md",
        "original_filename": "notes.md",
        "status": "SUCCESS",
        "step": "Done",
        "progress": 100,
        "error": "",
        "created_at": "2026-05-29T00:00:00+00:00",
        "updated_at": "2026-05-29T00:00:01+00:00",
        "finished_at": "2026-05-29T00:00:01+00:00",
    }
    client = _client(monkeypatch, FakeCelery())
    monkeypatch.setattr("app.api.endpoints.jobs.job_repository", FakeJobRepository(row))

    response = client.get("/api/v1/jobs/")

    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["jobs"][0]["job_id"] == "job-1"
