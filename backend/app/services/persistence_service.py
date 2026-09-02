"""Small persistence helpers for the first DB-backed records.

The app still reads document lists from sidecar JSON for now. These helpers
mirror users and documents into SQLAlchemy tables so the database layer can
grow without forcing a risky rewrite of upload/search/graph in one pass.
"""

from __future__ import annotations

import logging
import uuid
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


def save_oauth_identity(provider: str, provider_user_id: str, user_id: str) -> None:
    """Link an external account to the local user that owns its workspace."""
    if not db_enabled():
        return

    from sqlalchemy import select
    from app.models.persistence import OAuthIdentityRecord

    identity_id = f"{provider}:{provider_user_id}"
    with SessionLocal() as db:  # type: ignore[misc]
        record = db.get(OAuthIdentityRecord, identity_id)
        if not record:
            record = db.scalars(
                select(OAuthIdentityRecord).where(
                    OAuthIdentityRecord.provider == provider,
                    OAuthIdentityRecord.provider_user_id == provider_user_id,
                )
            ).first()
        if record:
            record.user_id = user_id
        else:
            db.add(
                OAuthIdentityRecord(
                    id=identity_id,
                    provider=provider,
                    provider_user_id=provider_user_id,
                    user_id=user_id,
                )
            )
        db.commit()


def load_user_by_oauth(provider: str, provider_user_id: str) -> dict[str, Any] | None:
    """Load the local account already linked to an external identity."""
    if not db_enabled():
        return None

    from sqlalchemy import select
    from app.models.persistence import OAuthIdentityRecord, UserRecord

    try:
        with SessionLocal() as db:  # type: ignore[misc]
            identity = db.scalars(
                select(OAuthIdentityRecord).where(
                    OAuthIdentityRecord.provider == provider,
                    OAuthIdentityRecord.provider_user_id == provider_user_id,
                )
            ).first()
            if not identity:
                return None
            record = db.get(UserRecord, identity.user_id)
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
        log.warning("Could not load OAuth identity: %s", exc)
        return None


def save_document_record(metadata: dict[str, Any]) -> None:
    """Mirror uploaded document metadata into the documents table."""
    if not db_enabled():
        return

    from sqlalchemy import select
    from app.models.persistence import DocumentRecord

    user_id = str(metadata.get("user_id") or "local-dev")
    document_id = str(metadata.get("document_id") or "")
    file_hash = str(metadata.get("file_hash") or "")
    with SessionLocal() as db:  # type: ignore[misc]
        existing = None
        if document_id:
            existing = db.scalars(
                select(DocumentRecord).where(
                    DocumentRecord.id == document_id,
                    DocumentRecord.user_id == user_id,
                )
            ).first()
        if not existing and file_hash:
            existing = db.scalars(
                select(DocumentRecord).where(
                    DocumentRecord.user_id == user_id,
                    DocumentRecord.file_hash == file_hash,
                )
            ).first()

        values = _document_values(metadata)
        if existing:
            for key, value in values.items():
                setattr(existing, key, value)
        else:
            existing = DocumentRecord(id=uuid.uuid4().hex, **values)
            db.add(existing)
        metadata["document_id"] = existing.id
        db.commit()


def mark_document_deleted(filename: str, user_id: str) -> None:
    """Soft-delete a document record after local storage removes the file."""
    if not db_enabled():
        return

    from sqlalchemy import select
    from app.models.persistence import DocumentRecord

    with SessionLocal() as db:  # type: ignore[misc]
        record = db.scalars(
            select(DocumentRecord).where(
                DocumentRecord.filename == filename,
                DocumentRecord.user_id == user_id,
            )
        ).first()
        if record:
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
