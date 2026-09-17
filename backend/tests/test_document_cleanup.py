"""Regression tests for retrying all document-derived cleanup."""

from types import SimpleNamespace

import pytest

from app.tasks import document_cleanup


def _run_task(task, *args):
    runner = getattr(task, "run", task)
    return runner(*args)


def test_cleanup_tasks_retry_all_derived_data(monkeypatch):
    calls = []

    def cleanup(document_id, *, user_id, workspace_id):
        calls.append((document_id, user_id, workspace_id))
        return True

    monkeypatch.setattr(
        document_cleanup.document_service,
        "run_deleted_document_cleanup",
        cleanup,
    )

    for task in (
        document_cleanup.retry_document_cleanup,
        document_cleanup.retry_visit_preparation_cleanup,
    ):
        result = _run_task(task, "doc-1", "user-1", "workspace-1")
        assert result == {"document_id": "doc-1", "status": "completed"}

    assert calls == [
        ("doc-1", "user-1", "workspace-1"),
        ("doc-1", "user-1", "workspace-1"),
    ]


def test_cleanup_task_retries_after_worker_failure(monkeypatch):
    class RetryRequested(Exception):
        pass

    def fail_cleanup(*_args, **_kwargs):
        raise RuntimeError("database unavailable")

    class RetryContext:
        request = SimpleNamespace(retries=1)

        def retry(self, **kwargs):
            raise RetryRequested(kwargs)

    monkeypatch.setattr(
        document_cleanup.document_service,
        "run_deleted_document_cleanup",
        fail_cleanup,
    )

    with pytest.raises(RetryRequested) as exc:
        document_cleanup._run_document_cleanup_retry(
            RetryContext(),
            document_id="doc-1",
            user_id="user-1",
            workspace_id="workspace-1",
        )

    assert exc.value.args[0]["countdown"] == 120


def test_pending_cleanup_sweep_leaves_candidate_when_broker_is_unavailable(monkeypatch):
    candidate = {
        "document_id": "doc-1",
        "user_id": "user-1",
        "workspace_id": "workspace-1",
    }
    published = []

    monkeypatch.setattr(
        document_cleanup.document_repository,
        "list_cleanup_candidates",
        lambda *, limit: [candidate],
    )

    def fail_publish(**_kwargs):
        published.append(candidate)
        raise RuntimeError("broker unavailable")

    monkeypatch.setattr(
        document_cleanup.retry_document_cleanup,
        "apply_async",
        fail_publish,
    )

    result = document_cleanup.retry_pending_document_cleanups.run(limit=10)

    assert result == {
        "status": "completed",
        "candidates": 1,
        "queued": 0,
        "publish_failures": 1,
    }
    assert published == [candidate]
