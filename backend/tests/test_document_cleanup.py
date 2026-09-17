"""Regression tests for retrying all document-derived cleanup."""

from app.tasks import document_cleanup


def _run_task(task, *args):
    runner = getattr(task, "run", task)
    return runner(*args)


def test_cleanup_tasks_retry_all_derived_data(monkeypatch):
    calls = []

    def cleanup(document_id, *, user_id, workspace_id):
        calls.append((document_id, user_id, workspace_id))

    monkeypatch.setattr(
        document_cleanup.document_service,
        "cleanup_deleted_document_data",
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
