"""Database-backed document metadata repository.

File bytes still live in FileStorage. This repository owns the metadata read
path so the API can move away from scanning sidecar JSON files on every list,
detail, search, graph, and chat request.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Callable, Optional

from app.core.database import SessionLocal, db_enabled
from app.core.errors import DatabaseOperationError

log = logging.getLogger(__name__)

try:
    from sqlalchemy import select
    from sqlalchemy.exc import SQLAlchemyError
    from app.models.persistence import DocumentRecord
except ImportError:  # pragma: no cover - only before DB deps are installed
    select = None
    SQLAlchemyError = Exception
    DocumentRecord = None  # type: ignore[assignment]


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
        # Import-time DB dependencies are optional in local development, so the
        # repository can be present without being usable.
        return bool(self.enabled() and self.session_factory and DocumentRecord and select)

    def save_metadata(self, metadata: dict[str, Any]) -> None:
        if not self.available():
            return

        user_id = str(metadata.get("user_id") or "local-dev")
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
                        )
                    ).first()
                if not record and file_hash:
                    # A soft-deleted row can be reused when the same bytes are
                    # uploaded again. The uniqueness check is still per user.
                    record = db.scalars(
                        select(DocumentRecord).where(
                            DocumentRecord.user_id == user_id,
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

    def list(self, user_id: Optional[str]) -> list[dict[str, Any]]:
        if not self.available():
            return []

        try:
            with self.session_factory() as db:
                stmt = select(DocumentRecord).where(DocumentRecord.deleted_at.is_(None))
                if user_id:
                    stmt = stmt.where(DocumentRecord.user_id == user_id)
                stmt = stmt.order_by(DocumentRecord.created_at.desc())
                return [_record_to_metadata(record) for record in db.scalars(stmt).all()]
        except (SQLAlchemyError, OSError, RuntimeError) as exc:
            _raise_db_error("list document metadata", exc, {"user_id": user_id or ""})

    def get(self, filename: str, user_id: Optional[str]) -> Optional[dict[str, Any]]:
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
                record = db.scalars(stmt).first()
                return _record_to_metadata(record) if record else None
        except (SQLAlchemyError, OSError, RuntimeError) as exc:
            _raise_db_error("get document metadata", exc, {"filename": filename})

    def get_by_id(self, document_id: str, user_id: Optional[str]) -> Optional[dict[str, Any]]:
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
                record = db.scalars(stmt).first()
                return _record_to_metadata(record) if record else None
        except (SQLAlchemyError, OSError, RuntimeError) as exc:
            _raise_db_error("get document metadata by id", exc, {"document_id": document_id})

    def has_any(self, user_id: Optional[str]) -> bool:
        """Return whether this user has any DB document records, including deleted ones."""
        if not self.available():
            return False

        try:
            with self.session_factory() as db:
                stmt = select(DocumentRecord.id)
                if user_id:
                    stmt = stmt.where(DocumentRecord.user_id == user_id)
                return db.scalars(stmt).first() is not None
        except (SQLAlchemyError, OSError, RuntimeError) as exc:
            _raise_db_error("check document metadata", exc, {"user_id": user_id or ""})

    def has_record(self, filename: str, user_id: Optional[str]) -> bool:
        """Return whether a DB row exists for this filename, even if soft-deleted."""
        if not self.available():
            return False

        try:
            with self.session_factory() as db:
                stmt = select(DocumentRecord.id).where(DocumentRecord.filename == filename)
                if user_id:
                    stmt = stmt.where(DocumentRecord.user_id == user_id)
                return db.scalars(stmt).first() is not None
        except (SQLAlchemyError, OSError, RuntimeError) as exc:
            _raise_db_error("check document metadata record", exc, {"filename": filename})

    def get_by_hash(self, file_hash: str, user_id: Optional[str]) -> Optional[dict[str, Any]]:
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
                record = db.scalars(stmt).first()
                return _record_to_metadata(record) if record else None
        except (SQLAlchemyError, OSError, RuntimeError) as exc:
            _raise_db_error("get document metadata by hash", exc, {"file_hash": file_hash})

    def mark_deleted(self, filename: str, user_id: Optional[str]) -> None:
        if not self.available():
            return

        from app.models.persistence import utc_now

        try:
            with self.session_factory() as db:
                stmt = select(DocumentRecord).where(DocumentRecord.filename == filename)
                if user_id:
                    stmt = stmt.where(DocumentRecord.user_id == user_id)
                record = db.scalars(stmt).first()
                if record:
                    record.deleted_at = utc_now()
                    db.commit()
        except (SQLAlchemyError, OSError, RuntimeError) as exc:
            _raise_db_error("mark document deleted", exc, {"filename": filename})


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
        "created_at": record.created_at.isoformat() if record.created_at else "",
        "modified_at": record.modified_at.isoformat() if record.modified_at else "",
        "status": record.status,
    }


def _raise_db_error(operation: str, exc: Exception, details: dict[str, Any]) -> None:
    # Once a request chooses the DB path, silently falling back to sidecars can
    # resurrect deleted documents or hide writes. Surface the dependency failure.
    log.warning("Could not %s: %s", operation, exc)
    raise DatabaseOperationError(
        "Document metadata database is unavailable.",
        details={"operation": operation, **details},
    ) from exc


document_repository = DocumentRepository()
