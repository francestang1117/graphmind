"""Database-backed history for background jobs."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any, Callable, Optional

from app.core.database import SessionLocal, db_enabled
from app.core.errors import DatabaseOperationError

log = logging.getLogger(__name__)

try:
    from sqlalchemy import delete, select
    from sqlalchemy.exc import SQLAlchemyError
    from app.models.persistence import ProcessingJobRecord, utc_now
except ImportError:  # pragma: no cover - only before DB deps are installed
    delete = None
    select = None
    SQLAlchemyError = Exception
    ProcessingJobRecord = None  # type: ignore[assignment]
    utc_now = None  # type: ignore[assignment]


TERMINAL_STATES = {"SUCCESS", "FAILURE", "REVOKED", "ERROR"}


class JobRepository:
    """Small repository for task state that should survive page refreshes."""

    def __init__(
        self,
        session_factory=SessionLocal,
        enabled: Callable[[], bool] = db_enabled,
    ) -> None:
        self.session_factory = session_factory
        self.enabled = enabled

    def available(self) -> bool:
        return bool(
            self.enabled()
            and self.session_factory
            and ProcessingJobRecord
            and select
            and utc_now
        )

    def create(
        self,
        job_id: str,
        *,
        user_id: str,
        document_id: str = "",
        original_filename: str = "",
        status: str = "PENDING",
        step: str = "Queued",
        progress: int = 0,
    ) -> None:
        self.upsert(
            job_id,
            user_id=user_id,
            document_id=document_id,
            original_filename=original_filename,
            status=status,
            step=step,
            progress=progress,
        )

    def upsert(
        self,
        job_id: str,
        *,
        user_id: str = "",
        document_id: str = "",
        original_filename: str = "",
        status: str,
        step: str,
        progress: int,
        error: str = "",
    ) -> None:
        if not self.available():
            return

        now = utc_now()
        # Progress can arrive from Celery, tests, or future maintenance tasks.
        # Clamp it here once so callers do not each need their own guard.
        values = {
            "user_id": user_id,
            "document_id": document_id,
            "original_filename": original_filename,
            "status": status,
            "step": step,
            "progress": max(0, min(100, int(progress))),
            "error": error,
            "updated_at": now,
            "finished_at": now if status in TERMINAL_STATES else None,
        }
        try:
            with self.session_factory() as db:
                record = db.get(ProcessingJobRecord, job_id)
                if record:
                    for key, value in values.items():
                        # Later progress updates often only know status/step.
                        # Do not wipe filename/user fields with blanks.
                        if value != "" or key in {"status", "step", "progress", "error", "updated_at", "finished_at"}:
                            setattr(record, key, value)
                else:
                    db.add(ProcessingJobRecord(job_id=job_id, created_at=now, **values))
                db.commit()
        except (SQLAlchemyError, OSError, RuntimeError) as exc:
            _raise_db_error("save job state", exc, {"job_id": job_id})

    def list(self, user_id: Optional[str], limit: int = 50) -> list[dict[str, Any]]:
        if not self.available():
            return []

        try:
            with self.session_factory() as db:
                stmt = select(ProcessingJobRecord)
                if user_id:
                    stmt = stmt.where(ProcessingJobRecord.user_id == user_id)
                stmt = stmt.order_by(ProcessingJobRecord.created_at.desc()).limit(limit)
                return [_record_to_dict(record) for record in db.scalars(stmt).all()]
        except (SQLAlchemyError, OSError, RuntimeError) as exc:
            _raise_db_error("list job history", exc, {"user_id": user_id or ""})

    def get(self, job_id: str, user_id: Optional[str]) -> Optional[dict[str, Any]]:
        if not self.available():
            return None

        try:
            with self.session_factory() as db:
                stmt = select(ProcessingJobRecord).where(ProcessingJobRecord.job_id == job_id)
                if user_id:
                    stmt = stmt.where(ProcessingJobRecord.user_id == user_id)
                record = db.scalars(stmt).first()
                return _record_to_dict(record) if record else None
        except (SQLAlchemyError, OSError, RuntimeError) as exc:
            _raise_db_error("get job history", exc, {"job_id": job_id})

    def cleanup_finished(self, older_than_days: int = 30) -> int:
        if not self.available() or delete is None:
            return 0

        cutoff = utc_now() - timedelta(days=older_than_days)
        try:
            with self.session_factory() as db:
                # Keep active rows no matter how old they look. A stuck job
                # should stay visible until a person or worker marks it done.
                stmt = delete(ProcessingJobRecord).where(
                    ProcessingJobRecord.status.in_(TERMINAL_STATES),
                    ProcessingJobRecord.finished_at.is_not(None),
                    ProcessingJobRecord.finished_at < cutoff,
                )
                result = db.execute(stmt)
                db.commit()
                return int(result.rowcount or 0)
        except (SQLAlchemyError, OSError, RuntimeError) as exc:
            _raise_db_error("cleanup job history", exc, {"older_than_days": older_than_days})


def _record_to_dict(record: ProcessingJobRecord) -> dict[str, Any]:
    return {
        "job_id": record.job_id,
        "user_id": record.user_id,
        "document_id": record.document_id,
        "original_filename": record.original_filename,
        "status": record.status,
        "step": record.step,
        "progress": record.progress,
        "error": record.error,
        "created_at": record.created_at.isoformat() if record.created_at else "",
        "updated_at": record.updated_at.isoformat() if record.updated_at else "",
        "finished_at": record.finished_at.isoformat() if record.finished_at else None,
    }


def _raise_db_error(operation: str, exc: Exception, details: dict[str, Any]) -> None:
    log.warning("Could not %s: %s", operation, exc)
    raise DatabaseOperationError(
        "Job history database is unavailable.",
        details={"operation": operation, **details},
    ) from exc


job_repository = JobRepository()
