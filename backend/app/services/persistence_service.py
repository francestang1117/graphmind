"""Small persistence helpers for the first DB-backed records.

The app still reads document lists from sidecar JSON for now. These helpers
mirror users and documents into SQLAlchemy tables so the database layer can
grow without forcing a risky rewrite of upload/search/graph in one pass.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from app.core.database import SessionLocal, db_enabled

log = logging.getLogger(__name__)


def save_user_record(user: Any) -> None:
    """Mirror an auth user into the users table when DB persistence is enabled."""
    if not db_enabled():
        return

    from sqlalchemy import select
    from app.models.persistence import UserRecord

    with SessionLocal() as db:  # type: ignore[misc]
        existing = db.get(UserRecord, user.id)
        if not existing:
            existing = db.scalars(select(UserRecord).where(UserRecord.email == user.email)).first()
        if existing:
            # Keep the same user id after an API restart; access tokens use it
            # to find the persisted account again.
            user.id = existing.id
            existing.email = user.email
            existing.name = user.name
            existing.hashed_password = user.hashed_password
        else:
            db.add(
                UserRecord(
                    id=user.id,
                    email=user.email,
                    name=user.name,
                    hashed_password=user.hashed_password,
                    created_at=_parse_dt(user.created_at),
                )
            )
        db.commit()


def load_user_record(*, user_id: str | None = None, email: str | None = None) -> dict[str, Any] | None:
    """Read one account back into the local auth layer."""
    if not db_enabled() or (not user_id and not email):
        return None

    from sqlalchemy import select
    from app.models.persistence import UserRecord

    try:
        with SessionLocal() as db:  # type: ignore[misc]
            if user_id:
                record = db.get(UserRecord, user_id)
            else:
                record = db.scalars(select(UserRecord).where(UserRecord.email == email)).first()
            if not record:
                return None
            return {
                "id": record.id,
                "email": record.email,
                "name": record.name,
                "hashed_password": record.hashed_password,
                "created_at": record.created_at.isoformat(),
            }
    except Exception as exc:
        # Local development can continue with the in-process account cache.
        log.warning("Could not load user record: %s", exc)
        return None


def save_document_record(metadata: dict[str, Any]) -> None:
    """Mirror uploaded document metadata into the documents table."""
    if not db_enabled():
        return

    from app.models.persistence import DocumentRecord

    record_id = metadata.get("stored_filename") or metadata["filename"]
    with SessionLocal() as db:  # type: ignore[misc]
        existing = db.get(DocumentRecord, record_id)
        values = _document_values(metadata)
        if existing:
            for key, value in values.items():
                setattr(existing, key, value)
        else:
            db.add(DocumentRecord(id=record_id, **values))
        db.commit()


def mark_document_deleted(filename: str, user_id: str) -> None:
    """Soft-delete a document record after local storage removes the file."""
    if not db_enabled():
        return

    from app.models.persistence import DocumentRecord

    with SessionLocal() as db:  # type: ignore[misc]
        record = db.get(DocumentRecord, filename)
        if record and record.user_id == user_id:
            record.deleted_at = datetime.now(timezone.utc)
            db.commit()


def _document_values(metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        "user_id": metadata.get("user_id", "local-dev"),
        "filename": metadata.get("filename", ""),
        "stored_filename": metadata.get("stored_filename", metadata.get("filename", "")),
        "original_filename": metadata.get("original_filename", ""),
        "file_extension": metadata.get("file_extension", ""),
        "file_type": metadata.get("file_type", ""),
        "mime_type": metadata.get("mime_type", ""),
        "file_hash": metadata.get("file_hash", ""),
        "file_path": metadata.get("file_path", ""),
        "file_size": int(metadata.get("file_size", 0) or 0),
        "status": metadata.get("status", "uploaded"),
        "created_at": _parse_dt(metadata.get("created_at")),
        "modified_at": _parse_dt(metadata.get("modified_at")),
        "deleted_at": None,
    }


def _parse_dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            log.debug("Could not parse datetime value %r", value)
    return datetime.now(timezone.utc)
