"""Celery wiring, with a tiny local fallback."""

from functools import wraps
from typing import Any, Callable

from app.core.config import settings


class LocalTaskQueue:
    """Small stand-in used when Celery is not installed."""

    def __init__(self) -> None:
        self.control = LocalTaskControl()

    def task(self, *_args: Any, **kwargs: Any) -> Callable:
        bind = bool(kwargs.get("bind"))

        def decorator(func: Callable) -> Callable:
            @wraps(func)
            def run(*args: Any, **call_kwargs: Any) -> Any:
                if bind:
                    return func(LocalTaskContext(), *args, **call_kwargs)
                return func(*args, **call_kwargs)

            run.delay = run  # type: ignore[attr-defined]
            return run

        return decorator

    def AsyncResult(self, _job_id: str) -> "LocalTaskResult":
        return LocalTaskResult()


class LocalTaskContext:
    """Enough of Celery's task API for local progress-aware tasks."""

    def __init__(self) -> None:
        self.state = "PENDING"
        self.info: dict[str, Any] = {}

    def update_state(self, state: str, meta: dict[str, Any]) -> None:
        self.state = state
        self.info = meta


class LocalTaskControl:
    """Local mode has nothing to revoke, but the API can keep one shape."""

    def revoke(self, *_args: Any, **_kwargs: Any) -> None:
        return None


class LocalTaskResult:
    """Fallback shape for the WebSocket route when no worker exists."""

    state = "PENDING"
    info: dict[str, Any] = {}
    result: dict[str, Any] = {}


try:
    from celery import Celery
except ImportError:
    celery_app = LocalTaskQueue()
else:
    broker_url = getattr(settings, "CELERY_BROKER_URL", "memory://")
    result_backend = getattr(settings, "CELERY_RESULT_BACKEND", "cache+memory://")

    celery_app = Celery(
        "graphmind",
        broker=broker_url,
        backend=result_backend,
        include=["app.tasks.process_document"],
    )
    celery_app.conf.update(
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        timezone="UTC",
        enable_utc=True,
        task_track_started=True,
        task_default_queue=settings.CELERY_TASK_DEFAULT_QUEUE,
        task_routes={
            "app.tasks.process_document.*": {"queue": settings.CELERY_TASK_DEFAULT_QUEUE},
        },
    )
    # Beat is opt-in. Reindexing is useful, but local dev should not suddenly
    # wake up and reprocess uploads just because Celery is installed.
    if settings.CELERY_REINDEX_ENABLED:
        celery_app.conf.beat_schedule = {
            "reindex-all-documents": {
                "task": "app.tasks.process_document.reindex_all_documents",
                "schedule": settings.CELERY_REINDEX_INTERVAL_SECONDS,
            }
        }
