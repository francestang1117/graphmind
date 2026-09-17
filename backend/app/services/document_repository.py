"""Database-backed document metadata repository.

File bytes still live in FileStorage. This repository owns the metadata read
path so the API can move away from scanning sidecar JSON files on every list,
detail, search, graph, and chat request.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional

from app.core.database import SessionLocal, db_enabled
from app.core.errors import DatabaseOperationError

log = logging.getLogger(__name__)

try:
    from sqlalchemy import or_, select
    from sqlalchemy.exc import SQLAlchemyError
    from app.models.persistence import DocumentRecord
except ImportError:  # pragma: no cover - only before DB deps are installed
    or_ = None
    select = None
    SQLAlchemyError = Exception
    DocumentRecord = None  # type: ignore[assignment]

CLEANUP_NOT_REQUIRED = "not_required"
CLEANUP_PENDING = "pending"
CLEANUP_RUNNING = "running"
CLEANUP_COMPLETED = "completed"
CLEANUP_FAILED = "failed"
CLEANUP_LEASE_SECONDS = 300


class DocumentRepository:
    """Small SQLAlchemy repository for the documents table."""

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
            and DocumentRecord
            and or_
            and select
        )

    def save_metadata(self, metadata: dict[str, Any]) -> None:
        if not self.available():
            return

        user_id = str(metadata.get("user_id") or "local-dev")
        workspace_id = str(metadata.get("workspace_id") or _default_workspace(user_id))
        metadata["workspace_id"] = workspace_id
        document_id = str(metadata.get("document_id") or "")
        file_hash = str(metadata.get("file_hash") or "")
        try:
            with self.session_factory() as db:
                record = None
                if document_id:
                    record = db.scalars(
                        select(DocumentRecord).where(
                            DocumentRecord.id == document_id,
                            DocumentRecord.user_id == user_id,
                            DocumentRecord.workspace_id == workspace_id,
                        )
                    ).first()
                if not record and file_hash:
                    # A soft-deleted row can be reused when the same bytes are
                    # uploaded again. The uniqueness check is still per user.
                    record = db.scalars(
                        select(DocumentRecord).where(
                            DocumentRecord.user_id == user_id,
                            DocumentRecord.workspace_id == workspace_id,
                            DocumentRecord.file_hash == file_hash,
                        )
                    ).first()

                values = _document_values(metadata)
                if record:
                    for key, value in values.items():
                        setattr(record, key, value)
                else:
                    record = DocumentRecord(id=uuid.uuid4().hex, **values)
                    db.add(record)

                # The worker and parsed-artifact tables use this stable ID;
                # stored filenames remain a storage/API concern.
                metadata["document_id"] = record.id
                db.commit()
        except (SQLAlchemyError, OSError, RuntimeError) as exc:
            _raise_db_error(
                "save document metadata",
                exc,
                {"filename": metadata.get("stored_filename") or metadata.get("filename", "")},
            )

    def list(self, user_id: Optional[str], workspace_id: Optional[str] = None) -> list[dict[str, Any]]:
        if not self.available():
            return []

        try:
            with self.session_factory() as db:
                stmt = select(DocumentRecord).where(DocumentRecord.deleted_at.is_(None))
                if user_id:
                    stmt = stmt.where(DocumentRecord.user_id == user_id)
                    stmt = stmt.where(_workspace_condition(DocumentRecord.workspace_id, user_id, workspace_id))
                stmt = stmt.order_by(DocumentRecord.created_at.desc())
                return [_record_to_metadata(record) for record in db.scalars(stmt).all()]
        except (SQLAlchemyError, OSError, RuntimeError) as exc:
            _raise_db_error("list document metadata", exc, {"user_id": user_id or ""})

    def get(
        self,
        filename: str,
        user_id: Optional[str],
        workspace_id: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        if not self.available():
            return None

        try:
            with self.session_factory() as db:
                stmt = select(DocumentRecord).where(
                    DocumentRecord.deleted_at.is_(None),
                    DocumentRecord.filename == filename,
                )
                if user_id:
                    stmt = stmt.where(DocumentRecord.user_id == user_id)
                    stmt = stmt.where(_workspace_condition(DocumentRecord.workspace_id, user_id, workspace_id))
                record = db.scalars(stmt).first()
                return _record_to_metadata(record) if record else None
        except (SQLAlchemyError, OSError, RuntimeError) as exc:
            _raise_db_error("get document metadata", exc, {"filename": filename})

    def get_by_id(
        self,
        document_id: str,
        user_id: Optional[str],
        workspace_id: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        """Look up a document by its internal ID without crossing workspaces."""
        if not self.available():
            return None

        try:
            with self.session_factory() as db:
                stmt = select(DocumentRecord).where(
                    DocumentRecord.deleted_at.is_(None),
                    DocumentRecord.id == document_id,
                )
                if user_id:
                    stmt = stmt.where(DocumentRecord.user_id == user_id)
                    stmt = stmt.where(_workspace_condition(DocumentRecord.workspace_id, user_id, workspace_id))
                record = db.scalars(stmt).first()
                return _record_to_metadata(record) if record else None
        except (SQLAlchemyError, OSError, RuntimeError) as exc:
            _raise_db_error("get document metadata by id", exc, {"document_id": document_id})

    def has_any(self, user_id: Optional[str], workspace_id: Optional[str] = None) -> bool:
        """Return whether this user has any DB document records, including deleted ones."""
        if not self.available():
            return False

        try:
            with self.session_factory() as db:
                stmt = select(DocumentRecord.id)
                if user_id:
                    stmt = stmt.where(DocumentRecord.user_id == user_id)
                    stmt = stmt.where(_workspace_condition(DocumentRecord.workspace_id, user_id, workspace_id))
                return db.scalars(stmt).first() is not None
        except (SQLAlchemyError, OSError, RuntimeError) as exc:
            _raise_db_error("check document metadata", exc, {"user_id": user_id or ""})

    def has_record(
        self,
        filename: str,
        user_id: Optional[str],
        workspace_id: Optional[str] = None,
    ) -> bool:
        """Return whether a DB row exists for this filename, even if soft-deleted."""
        if not self.available():
            return False

        try:
            with self.session_factory() as db:
                stmt = select(DocumentRecord.id).where(DocumentRecord.filename == filename)
                if user_id:
                    stmt = stmt.where(DocumentRecord.user_id == user_id)
                    stmt = stmt.where(_workspace_condition(DocumentRecord.workspace_id, user_id, workspace_id))
                return db.scalars(stmt).first() is not None
        except (SQLAlchemyError, OSError, RuntimeError) as exc:
            _raise_db_error("check document metadata record", exc, {"filename": filename})

    def get_by_hash(
        self,
        file_hash: str,
        user_id: Optional[str],
        workspace_id: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        if not self.available():
            return None

        try:
            with self.session_factory() as db:
                stmt = select(DocumentRecord).where(
                    DocumentRecord.deleted_at.is_(None),
                    DocumentRecord.file_hash == file_hash,
                )
                if user_id:
                    stmt = stmt.where(DocumentRecord.user_id == user_id)
                    stmt = stmt.where(_workspace_condition(DocumentRecord.workspace_id, user_id, workspace_id))
                record = db.scalars(stmt).first()
                return _record_to_metadata(record) if record else None
        except (SQLAlchemyError, OSError, RuntimeError) as exc:
            _raise_db_error("get document metadata by hash", exc, {"file_hash": file_hash})

    def mark_deleted(
        self,
        filename: str,
        user_id: Optional[str],
        workspace_id: Optional[str] = None,
    ) -> None:
        if not self.available():
            return

        from app.models.persistence import utc_now

        try:
            with self.session_factory() as db:
                stmt = select(DocumentRecord).where(DocumentRecord.filename == filename)
                if user_id:
                    stmt = stmt.where(DocumentRecord.user_id == user_id)
                    stmt = stmt.where(_workspace_condition(DocumentRecord.workspace_id, user_id, workspace_id))
                record = db.scalars(stmt).first()
                if record:
                    now = utc_now()
                    record.deleted_at = now
                    # This update shares the transaction with the tombstone,
                    # so a lost broker cannot erase the cleanup obligation.
                    record.cleanup_status = CLEANUP_PENDING
                    record.cleanup_attempts = 0
                    record.cleanup_next_retry_at = None
                    record.cleanup_last_error = None
                    record.modified_at = now
                    db.commit()
        except (SQLAlchemyError, OSError, RuntimeError) as exc:
            _raise_db_error("mark document deleted", exc, {"filename": filename})

    def claim_cleanup(
        self,
        document_id: str,
        user_id: str,
        workspace_id: Optional[str] = None,
        *,
        now: Optional[datetime] = None,
        lease_seconds: int = CLEANUP_LEASE_SECONDS,
    ) -> bool:
        """Claim one due cleanup row so duplicate workers do not overlap."""
        if not self.available() or not document_id:
            return False

        current_time = now or datetime.now(timezone.utc)
        lease_until = current_time + timedelta(seconds=max(1, int(lease_seconds)))
        try:
            with self.session_factory() as db:
                due = or_(
                    DocumentRecord.cleanup_next_retry_at.is_(None),
                    DocumentRecord.cleanup_next_retry_at <= current_time,
                )
                stmt = select(DocumentRecord).where(
                    DocumentRecord.id == document_id,
                    DocumentRecord.user_id == user_id,
                    DocumentRecord.deleted_at.is_not(None),
                    due,
                    or_(
                        DocumentRecord.cleanup_status.is_(None),
                        DocumentRecord.cleanup_status.in_(
                            (CLEANUP_PENDING, CLEANUP_FAILED, CLEANUP_RUNNING)
                        ),
                    ),
                )
                if workspace_id is not None:
                    stmt = stmt.where(DocumentRecord.workspace_id == workspace_id)
                record = db.scalars(stmt.with_for_update()).first()
                if not record:
                    return False

                record.cleanup_status = CLEANUP_RUNNING
                record.cleanup_attempts = int(record.cleanup_attempts or 0) + 1
                record.cleanup_next_retry_at = lease_until
                record.cleanup_last_error = None
                record.modified_at = current_time
                db.commit()
                return True
        except (SQLAlchemyError, OSError, RuntimeError) as exc:
            _raise_db_error(
                "claim document cleanup",
                exc,
                {"document_id": document_id},
            )

    def list_cleanup_candidates(
        self,
        limit: int = 100,
        *,
        now: Optional[datetime] = None,
    ) -> list[dict[str, Any]]:
        """List due tombstones for the periodic compensation task."""
        if not self.available():
            return []

        current_time = now or datetime.now(timezone.utc)
        try:
            with self.session_factory() as db:
                due = or_(
                    DocumentRecord.cleanup_next_retry_at.is_(None),
                    DocumentRecord.cleanup_next_retry_at <= current_time,
                )
                stmt = (
                    select(DocumentRecord)
                    .where(
                        DocumentRecord.deleted_at.is_not(None),
                        due,
                        or_(
                            DocumentRecord.cleanup_status.is_(None),
                            DocumentRecord.cleanup_status.in_(
                                (CLEANUP_PENDING, CLEANUP_FAILED, CLEANUP_RUNNING)
                            ),
                        ),
                    )
                    .order_by(DocumentRecord.id)
                    .limit(max(1, min(int(limit or 100), 1000)))
                )
                return [
                    {
                        "document_id": record.id,
                        "user_id": record.user_id,
                        "workspace_id": record.workspace_id,
                    }
                    for record in db.scalars(stmt).all()
                ]
        except (SQLAlchemyError, OSError, RuntimeError) as exc:
            _raise_db_error("list document cleanup candidates", exc, {})

    def mark_cleanup_completed(
        self,
        document_id: str,
        user_id: str,
        workspace_id: Optional[str] = None,
    ) -> None:
        """Persist that all derived data was removed for a tombstone."""
        self._update_cleanup_state(
            document_id,
            user_id,
            workspace_id,
            status=CLEANUP_COMPLETED,
            next_retry_at=None,
            last_error=None,
            operation="mark document cleanup completed",
        )

    def mark_cleanup_failed(
        self,
        document_id: str,
        user_id: str,
        workspace_id: Optional[str] = None,
        *,
        next_retry_at: datetime,
        error_code: str,
    ) -> None:
        """Persist a retryable failure without storing exception details."""
        self._update_cleanup_state(
            document_id,
            user_id,
            workspace_id,
            status=CLEANUP_FAILED,
            next_retry_at=next_retry_at,
            last_error=(str(error_code or "document_cleanup_failed")[:120]),
            operation="mark document cleanup failed",
        )

    def _update_cleanup_state(
        self,
        document_id: str,
        user_id: str,
        workspace_id: Optional[str],
        *,
        status: str,
        next_retry_at: Optional[datetime],
        last_error: Optional[str],
        operation: str,
    ) -> None:
        if not self.available() or not document_id:
            return

        try:
            with self.session_factory() as db:
                stmt = select(DocumentRecord).where(
                    DocumentRecord.id == document_id,
                    DocumentRecord.user_id == user_id,
                    DocumentRecord.deleted_at.is_not(None),
                )
                if workspace_id is not None:
                    stmt = stmt.where(DocumentRecord.workspace_id == workspace_id)
                record = db.scalars(stmt).first()
                if not record:
                    return

                record.cleanup_status = status
                record.cleanup_next_retry_at = next_retry_at
                record.cleanup_last_error = last_error
                record.modified_at = datetime.now(timezone.utc)
                db.commit()
        except (SQLAlchemyError, OSError, RuntimeError) as exc:
            _raise_db_error(operation, exc, {"document_id": document_id})

    def has_other_active_copy(
        self,
        file_hash: str,
        user_id: str,
        exclude_document_id: str = "",
        workspace_id: Optional[str] = None,
    ) -> bool:
        """Tell storage whether another project still uses the same bytes."""
        if not self.available() or not file_hash:
            return False

        try:
            with self.session_factory() as db:
                stmt = select(DocumentRecord.id).where(
                    DocumentRecord.user_id == user_id,
                    DocumentRecord.file_hash == file_hash,
                    DocumentRecord.deleted_at.is_(None),
                )
                if workspace_id:
                    stmt = stmt.where(DocumentRecord.workspace_id == workspace_id)
                if exclude_document_id:
                    stmt = stmt.where(DocumentRecord.id != exclude_document_id)
                return db.scalars(stmt).first() is not None
        except (SQLAlchemyError, OSError, RuntimeError) as exc:
            _raise_db_error("check shared document bytes", exc, {"file_hash": file_hash})


def _document_values(metadata: dict[str, Any]) -> dict[str, Any]:
    from app.services.persistence_service import _document_values as values

    return values(metadata)


def _record_to_metadata(record: DocumentRecord) -> dict[str, Any]:
    return {
        "document_id": record.id,
        "filename": record.filename,
        "stored_filename": record.stored_filename,
        "original_filename": record.original_filename,
        "file_size": record.file_size,
        "file_extension": record.file_extension,
        "file_type": record.file_type,
        "file_hash": record.file_hash,
        "mime_type": record.mime_type,
        "file_path": record.file_path,
        "user_id": record.user_id,
        "workspace_id": record.workspace_id,
        "document_kind": record.document_kind,
        "source_kind": record.source_kind,
        "language": record.language,
        "document_date": record.document_date,
        "parser_version": record.parser_version,
        "created_at": record.created_at.isoformat() if record.created_at else "",
        "modified_at": record.modified_at.isoformat() if record.modified_at else "",
        "status": record.status,
        "deleted_at": record.deleted_at.isoformat() if record.deleted_at else None,
        "cleanup_status": record.cleanup_status,
        "cleanup_attempts": record.cleanup_attempts,
        "cleanup_next_retry_at": (
            record.cleanup_next_retry_at.isoformat()
            if record.cleanup_next_retry_at
            else None
        ),
        "cleanup_last_error": record.cleanup_last_error,
    }


def _default_workspace(user_id: str) -> str:
    from app.core.workspace import default_workspace_id

    return default_workspace_id(user_id)


def _workspace_condition(column, user_id: str, workspace_id: Optional[str]):
    """Match migrated rows and old NULL rows when no project was selected."""
    if workspace_id:
        return column == workspace_id
    default_id = _default_workspace(user_id)
    return or_(column == default_id, column.is_(None))


def _raise_db_error(operation: str, exc: Exception, details: dict[str, Any]) -> None:
    # Once a request chooses the DB path, silently falling back to sidecars can
    # resurrect deleted documents or hide writes. Surface the dependency failure.
    log.warning("Could not %s: %s", operation, exc)
    raise DatabaseOperationError(
        "Document metadata database is unavailable.",
        details={"operation": operation, **details},
    ) from exc


document_repository = DocumentRepository()
