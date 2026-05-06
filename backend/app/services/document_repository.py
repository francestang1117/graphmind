"""Database-backed document metadata repository.

File bytes still live in FileStorage. This repository owns the metadata read
path so the API can move away from scanning sidecar JSON files on every list,
detail, search, graph, and chat request.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from app.core.database import SessionLocal, db_enabled

try:
    from sqlalchemy import select
    from app.models.persistence import DocumentRecord
except ImportError:  # pragma: no cover - only before DB deps are installed
    select = None
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
        return bool(self.enabled() and self.session_factory and DocumentRecord and select)

    def save_metadata(self, metadata: dict[str, Any]) -> None:
        if not self.available():
            return

        record_id = metadata.get("stored_filename") or metadata["filename"]
        with self.session_factory() as db:
            record = db.get(DocumentRecord, record_id)
            values = _document_values(metadata)
            if record:
                for key, value in values.items():
                    setattr(record, key, value)
            else:
                db.add(DocumentRecord(id=record_id, **values))
            db.commit()

    def list(self, user_id: Optional[str]) -> list[dict[str, Any]]:
        if not self.available():
            return []

        with self.session_factory() as db:
            stmt = select(DocumentRecord).where(DocumentRecord.deleted_at.is_(None))
            if user_id:
                stmt = stmt.where(DocumentRecord.user_id == user_id)
            stmt = stmt.order_by(DocumentRecord.created_at.desc())
            return [_record_to_metadata(record) for record in db.scalars(stmt).all()]

    def get(self, filename: str, user_id: Optional[str]) -> Optional[dict[str, Any]]:
        if not self.available():
            return None

        with self.session_factory() as db:
            stmt = select(DocumentRecord).where(
                DocumentRecord.deleted_at.is_(None),
                DocumentRecord.filename == filename,
            )
            if user_id:
                stmt = stmt.where(DocumentRecord.user_id == user_id)
            record = db.scalars(stmt).first()
            return _record_to_metadata(record) if record else None

    def has_any(self, user_id: Optional[str]) -> bool:
        """Return whether this user has any DB document records, including deleted ones."""
        if not self.available():
            return False

        with self.session_factory() as db:
            stmt = select(DocumentRecord.id)
            if user_id:
                stmt = stmt.where(DocumentRecord.user_id == user_id)
            return db.scalars(stmt).first() is not None

    def has_record(self, filename: str, user_id: Optional[str]) -> bool:
        """Return whether a DB row exists for this filename, even if soft-deleted."""
        if not self.available():
            return False

        with self.session_factory() as db:
            stmt = select(DocumentRecord.id).where(DocumentRecord.filename == filename)
            if user_id:
                stmt = stmt.where(DocumentRecord.user_id == user_id)
            return db.scalars(stmt).first() is not None

    def get_by_hash(self, file_hash: str, user_id: Optional[str]) -> Optional[dict[str, Any]]:
        if not self.available():
            return None

        with self.session_factory() as db:
            stmt = select(DocumentRecord).where(
                DocumentRecord.deleted_at.is_(None),
                DocumentRecord.file_hash == file_hash,
            )
            if user_id:
                stmt = stmt.where(DocumentRecord.user_id == user_id)
            record = db.scalars(stmt).first()
            return _record_to_metadata(record) if record else None

    def mark_deleted(self, filename: str, user_id: Optional[str]) -> None:
        if not self.available():
            return

        from app.models.persistence import utc_now

        with self.session_factory() as db:
            stmt = select(DocumentRecord).where(DocumentRecord.filename == filename)
            if user_id:
                stmt = stmt.where(DocumentRecord.user_id == user_id)
            record = db.scalars(stmt).first()
            if record:
                record.deleted_at = utc_now()
                db.commit()


def _document_values(metadata: dict[str, Any]) -> dict[str, Any]:
    from app.services.persistence_service import _document_values as values

    return values(metadata)


def _record_to_metadata(record: DocumentRecord) -> dict[str, Any]:
    return {
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


document_repository = DocumentRepository()
