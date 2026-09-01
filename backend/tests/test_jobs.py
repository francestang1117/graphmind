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
        self.async_result_calls = []

    def AsyncResult(self, _job_id):
        self.async_result_calls.append(_job_id)
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
    fake = FakeCelery()
    client = _client(monkeypatch, fake)
    monkeypatch.setattr(
        "app.api.endpoints.jobs.job_repository",
        FakeJobRepository({
            "job_id": "job-1",
            "document_id": "doc-1",
            "original_filename": "notes.md",
            "status": "PROGRESS",
            "step": "Indexing chunks",
            "progress": 55,
            "error": "",
            "created_at": "",
            "updated_at": "",
            "finished_at": None,
        }),
    )

    response = client.get("/api/v1/jobs/job-1")

    assert response.status_code == 200
    assert response.json()["state"] == "PROGRESS"
    assert response.json()["job"]["document_id"] == "doc-1"
    assert fake.async_result_calls == ["job-1"]


def test_unknown_job_does_not_query_or_revoke_celery(monkeypatch):
    fake = FakeCelery()
    client = _client(monkeypatch, fake)

    response = client.get("/api/v1/jobs/other-user-job")

    assert response.status_code == 404
    assert fake.async_result_calls == []
    assert fake.control.revoked == []


def test_unknown_job_cannot_be_cancelled(monkeypatch):
    fake = FakeCelery()
    client = _client(monkeypatch, fake)

    response = client.post("/api/v1/jobs/other-user-job/cancel")

    assert response.status_code == 404
    assert fake.async_result_calls == []
    assert fake.control.revoked == []


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


def test_ws_ticket_requires_the_owned_job_and_returns_short_lived_ticket(monkeypatch):
    async def no_redis():
        return None

    monkeypatch.setattr("app.services.websocket_ticket._redis_client", no_redis)
    jobs = FakeJobRepository({
        "job_id": "job-1",
        "document_id": "doc-1",
        "original_filename": "notes.md",
        "status": "PROGRESS",
        "step": "Parsing",
        "progress": 25,
        "error": "",
        "created_at": "",
        "updated_at": "",
        "finished_at": None,
    })
    client = _client(monkeypatch, FakeCelery())
    monkeypatch.setattr("app.api.endpoints.jobs.job_repository", jobs)

    response = client.post("/api/v1/jobs/job-1/ws-ticket")

    assert response.status_code == 200
    assert response.json()["ticket"]
    assert response.json()["expires_in"] == 60
    assert response.headers["cache-control"] == "no-store"


def test_ws_ticket_does_not_query_celery_for_unknown_job(monkeypatch):
    fake = FakeCelery()
    client = _client(monkeypatch, fake)

    response = client.post("/api/v1/jobs/missing-job/ws-ticket")

    assert response.status_code == 404
    assert fake.async_result_calls == []
