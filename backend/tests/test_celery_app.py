"""Tests for the local task queue used without a Celery worker."""

from app.core.celery_app import LocalTaskQueue


def test_local_apply_async_passes_task_id_to_bound_task():
    queue = LocalTaskQueue()
    seen = {}

    @queue.task(bind=True)
    def task(self, value):
        seen["task_id"] = self.request.id
        return value

    result = task.apply_async(args=("done",), task_id="job-1")

    assert seen == {"task_id": "job-1"}
    assert result.id == "job-1"
    assert result.state == "SUCCESS"
    assert result.result == "done"


def test_local_async_result_starts_pending():
    result = LocalTaskQueue().AsyncResult("job-1")

    assert result.id == "job-1"
    assert result.state == "PENDING"
