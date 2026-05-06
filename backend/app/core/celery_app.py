"""Celery wiring, with a tiny local fallback."""

from typing import Any, Callable

from app.core.config import settings


class LocalTaskQueue:
    """Small stand-in used when Celery is not installed."""

    def task(self, *_args: Any, **_kwargs: Any) -> Callable:
        def decorator(func: Callable) -> Callable:
            func.delay = func  # type: ignore[attr-defined]
            return func

        return decorator


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
