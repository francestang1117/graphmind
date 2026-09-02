"""Job history repository tests."""

from datetime import timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.persistence import ProcessingJobRecord, utc_now
from app.services.job_repository import JobRepository


def _repo() -> JobRepository:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    return JobRepository(session_factory=session_factory, enabled=lambda: True)


def test_job_repository_creates_updates_and_lists_by_user():
    repo = _repo()

    repo.create(
        "job-1",
        user_id="u1",
        document_id="hash.md",
        original_filename="notes.md",
    )
    repo.create("job-2", user_id="u2", document_id="other.md")
    repo.upsert(
        "job-1",
        user_id="u1",
        document_id="hash.md",
        original_filename="notes.md",
        status="PROGRESS",
        step="Indexing chunks",
        progress=90,
    )

    listed = repo.list("u1")
    fetched = repo.get("job-1", "u1")

    assert [item["job_id"] for item in listed] == ["job-1"]
    assert fetched["document_id"] == "hash.md"
    assert fetched["status"] == "PROGRESS"
    assert fetched["progress"] == 90
    assert repo.get("job-1", "u2") is None


def test_job_repository_cleanup_only_removes_old_terminal_jobs():
    repo = _repo()
    repo.create("old", user_id="u1")
    repo.create("recent", user_id="u1")
    repo.create("running", user_id="u1")

    old_finished = utc_now() - timedelta(days=40)
    recent_finished = utc_now() - timedelta(days=2)
    with repo.session_factory() as db:
        old = db.get(ProcessingJobRecord, "old")
        old.status = "SUCCESS"
        old.finished_at = old_finished
        old.updated_at = old_finished

        recent = db.get(ProcessingJobRecord, "recent")
        recent.status = "FAILURE"
        recent.finished_at = recent_finished
        recent.updated_at = recent_finished

        running = db.get(ProcessingJobRecord, "running")
        running.status = "PROGRESS"
        running.updated_at = old_finished
        db.commit()

    assert repo.cleanup_finished(older_than_days=30) == 1
    assert repo.get("old", "u1") is None
    assert repo.get("recent", "u1") is not None
    assert repo.get("running", "u1") is not None


def test_job_repository_does_not_downgrade_terminal_state():
    repo = _repo()
    repo.create("job-1", user_id="u1")
    repo.upsert(
        "job-1",
        user_id="u1",
        status="SUCCESS",
        step="Done",
        progress=100,
    )

    # This is the late API write that used to turn a completed job back into
    # PENDING when a worker won the race.
    repo.create("job-1", user_id="u1", status="PENDING", step="Queued", progress=0)
    repo.upsert(
        "job-1",
        user_id="u1",
        status="PROGRESS",
        step="Parsing",
        progress=25,
    )

    fetched = repo.get("job-1", "u1")
    assert fetched["status"] == "SUCCESS"
    assert fetched["step"] == "Done"
    assert fetched["progress"] == 100
    assert fetched["finished_at"]


def test_job_repository_finds_active_jobs_and_keeps_revocation_visible():
    repo = _repo()
    repo.create("active", user_id="u1", document_id="doc-1")
    repo.create("done", user_id="u1", document_id="doc-1")
    repo.upsert(
        "done",
        user_id="u1",
        document_id="doc-1",
        status="SUCCESS",
        step="Done",
        progress=100,
    )
    repo.create("other-doc", user_id="u1", document_id="doc-2")

    assert [job["job_id"] for job in repo.list_for_document("doc-1", "u1")] == ["active"]
    assert repo.is_revoked("active", "u1") is False

    repo.upsert(
        "active",
        user_id="u1",
        document_id="doc-1",
        status="REVOKED",
        step="Cancelled",
        progress=0,
        error="Document deleted",
    )

    assert repo.list_for_document("doc-1", "u1") == []
    assert repo.is_revoked("active", "u1") is True
