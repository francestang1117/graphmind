"""Celery wiring, with a tiny local fallback."""

from functools import wraps
from typing import Any, Callable

from app.core.config import settings


class LocalTaskQueue:
    """Small stand-in used when Celery is not installed."""

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


class LocalTaskContext:
    """Enough of Celery's task API for local progress-aware tasks."""

    def __init__(self) -> None:
        self.state = "PENDING"
        self.info: dict[str, Any] = {}

    def update_state(self, state: str, meta: dict[str, Any]) -> None:
        self.state = state
        self.info = meta


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
    )
