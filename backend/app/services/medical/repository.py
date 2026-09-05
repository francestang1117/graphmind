"""Database access for medical document analysis results."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from app.core.database import SessionLocal, db_enabled
from app.core.workspace import default_workspace_id

log = logging.getLogger(__name__)

try:
    from sqlalchemy import delete, or_, select
    from sqlalchemy.exc import SQLAlchemyError
    from app.models.persistence import (
        DocumentRecord,
        DocumentSectionRecord,
        MedicalDocumentProfileRecord,
    )
except ImportError:  # pragma: no cover - only before DB dependencies are installed
    delete = None
    or_ = None
    select = None
    SQLAlchemyError = Exception
    DocumentRecord = None  # type: ignore[assignment]
    DocumentSectionRecord = None  # type: ignore[assignment]
    MedicalDocumentProfileRecord = None  # type: ignore[assignment]


class MedicalRepository:
    """Replace and read the medical view attached to one document."""

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
            and delete
            and or_
            and select
            and DocumentRecord
            and DocumentSectionRecord
            and MedicalDocumentProfileRecord
        )

    def replace_analysis(
        self,
        identifier: str,
        analysis: dict[str, Any],
        sections: list[dict[str, Any]],
        *,
        user_id: str = "local-dev",
        workspace_id: Optional[str] = None,
    ) -> bool:
        """Replace one document's profile and sections in one transaction."""
        if not self.available():
            return False

        try:
            with self.session_factory() as db:
                saved = replace_analysis_in_session(
                    db,
                    identifier,
                    analysis,
                    sections,
                    user_id=user_id,
                    workspace_id=workspace_id,
                )
                if not saved:
                    db.rollback()
                    return False
                db.commit()
                return True
        except (SQLAlchemyError, OSError, RuntimeError, ValueError) as exc:
            log.warning("Could not save medical analysis for %s: %s", identifier, exc)
            return False

    def get_analysis(
        self,
        identifier: str,
        *,
        user_id: str = "local-dev",
        workspace_id: Optional[str] = None,
    ) -> dict[str, Any] | None:
        """Return a live document's profile and ordered sections."""
        if not self.available():
            return None

        try:
            with self.session_factory() as db:
                document = _find_document(
                    db,
                    identifier,
                    user_id,
                    workspace_id=workspace_id,
                )
                if not document:
                    return None

                scope = document.workspace_id or default_workspace_id(user_id)
                profile = db.scalars(
                    select(MedicalDocumentProfileRecord).where(
                        MedicalDocumentProfileRecord.document_id == document.id,
                        MedicalDocumentProfileRecord.user_id == user_id,
                        MedicalDocumentProfileRecord.workspace_id == scope,
                    )
                ).first()
                if not profile:
                    return None

                section_rows = db.scalars(
                    select(DocumentSectionRecord)
                    .where(
                        DocumentSectionRecord.document_id == document.id,
                        DocumentSectionRecord.user_id == user_id,
                        DocumentSectionRecord.workspace_id == scope,
                    )
                    .order_by(DocumentSectionRecord.ordinal)
                ).all()

                return {
                    "document_id": document.id,
                    "workspace_id": scope,
                    "document_kind": profile.document_kind,
                    "confidence": profile.confidence,
                    "language": profile.language,
                    "classifier_version": profile.classifier_version,
                    "signals": _loads_list(profile.signals_json),
                    "warnings": _loads_list(profile.warnings_json),
                    "missing_sections": _loads_list(profile.missing_sections_json),
                    "sections": [_section_dict(row) for row in section_rows],
                }
        except (SQLAlchemyError, OSError, RuntimeError) as exc:
            log.warning("Could not load medical analysis for %s: %s", identifier, exc)
            return None

    def delete_for_document(
        self,
        identifier: str,
        *,
        user_id: str = "local-dev",
        workspace_id: Optional[str] = None,
    ) -> bool:
        """Remove analysis rows after a document is deleted; safe to repeat."""
        if not self.available():
            return False

        try:
            with self.session_factory() as db:
                document = _find_document(
                    db,
                    identifier,
                    user_id,
                    workspace_id=workspace_id,
                    include_deleted=True,
                    lock=True,
                )
                if not document:
                    return False

                scope = document.workspace_id or default_workspace_id(user_id)
                db.execute(
                    delete(MedicalDocumentProfileRecord).where(
                        MedicalDocumentProfileRecord.document_id == document.id,
                        MedicalDocumentProfileRecord.user_id == user_id,
                        MedicalDocumentProfileRecord.workspace_id == scope,
                    )
                )
                db.execute(
                    delete(DocumentSectionRecord).where(
                        DocumentSectionRecord.document_id == document.id,
                        DocumentSectionRecord.user_id == user_id,
                        DocumentSectionRecord.workspace_id == scope,
                    )
                )
                db.commit()
                return True
        except (SQLAlchemyError, OSError, RuntimeError) as exc:
            log.warning("Could not delete medical analysis for %s: %s", identifier, exc)
            return False


def replace_analysis_in_session(
    db,
    identifier: str,
    analysis: dict[str, Any],
    sections: list[dict[str, Any]],
    *,
    user_id: str = "local-dev",
    workspace_id: Optional[str] = None,
    document: Optional["DocumentRecord"] = None,
) -> bool:
    """Write medical rows without committing the caller's transaction."""
    if not all(
        (
            delete,
            or_,
            select,
            DocumentRecord,
            DocumentSectionRecord,
            MedicalDocumentProfileRecord,
        )
    ):
        return False

    if document is None:
        document = _find_document(
            db,
            identifier,
            user_id,
            workspace_id=workspace_id,
            lock=True,
        )
    if not document:
        log.info("Skipping medical analysis for missing document %s", identifier)
        return False

    scope = document.workspace_id or default_workspace_id(user_id)
    # Older rows may not have a workspace yet. Give them the same default
    # scope used by the rest of the compatibility path.
    if document.workspace_id is None:
        document.workspace_id = scope

    profile = db.scalars(
        select(MedicalDocumentProfileRecord).where(
            MedicalDocumentProfileRecord.document_id == document.id,
            MedicalDocumentProfileRecord.user_id == user_id,
            MedicalDocumentProfileRecord.workspace_id == scope,
        )
    ).first()
    if profile:
        db.delete(profile)
    db.execute(
        delete(DocumentSectionRecord).where(
            DocumentSectionRecord.document_id == document.id,
            DocumentSectionRecord.user_id == user_id,
            DocumentSectionRecord.workspace_id == scope,
        )
    )
    db.flush()

    db.add(
        MedicalDocumentProfileRecord(
            id=_new_id(),
            user_id=user_id,
            workspace_id=scope,
            document_id=document.id,
            document_kind=str(analysis.get("document_kind") or "unknown"),
            language=str(analysis.get("language") or "unknown"),
            confidence=float(analysis.get("confidence", 0) or 0),
            classifier_version=str(
                analysis.get("classifier_version") or "medical-rules-v1"
            ),
            signals_json=_json(analysis.get("signals", [])),
            warnings_json=_json(analysis.get("warnings", [])),
            missing_sections_json=_json(analysis.get("missing_sections", [])),
            created_at=_utc_now(),
            updated_at=_utc_now(),
        )
    )

    for index, section in enumerate(sections, start=1):
        db.add(
            _section_record(
                section,
                index,
                document_id=document.id,
                user_id=user_id,
                workspace_id=scope,
            )
        )

    # The document summary is updated in the same transaction as its details.
    document.document_kind = str(analysis.get("document_kind") or "unknown")
    document.language = str(analysis.get("language") or "unknown")
    document.parser_version = str(
        analysis.get("parser_version") or "medical-rules-v1"
    )
    document.modified_at = _utc_now()

    # A delete can win while parsing is in progress. The caller will roll back
    # any rows already staged in this session when this check fails.
    return _document_is_active(db, document.id, user_id, scope)


def _find_document(
    db,
    identifier: str,
    user_id: str,
    *,
    workspace_id: Optional[str] = None,
    include_deleted: bool = False,
    lock: bool = False,
) -> Optional["DocumentRecord"]:
    conditions = [
        DocumentRecord.user_id == user_id,
        or_(DocumentRecord.id == identifier, DocumentRecord.filename == identifier),
        _workspace_condition(DocumentRecord.workspace_id, user_id, workspace_id),
    ]
    if not include_deleted:
        conditions.append(DocumentRecord.deleted_at.is_(None))

    stmt = select(DocumentRecord).where(*conditions)
    if lock:
        stmt = stmt.with_for_update()
    return db.scalars(stmt).first()


def _document_is_active(db, document_id: str, user_id: str, workspace_id: str) -> bool:
    return (
        db.scalars(
            select(DocumentRecord.id).where(
                DocumentRecord.id == document_id,
                DocumentRecord.user_id == user_id,
                DocumentRecord.workspace_id == workspace_id,
                DocumentRecord.deleted_at.is_(None),
            )
        ).first()
        is not None
    )


def _section_record(
    section: dict[str, Any],
    ordinal: int,
    *,
    document_id: str,
    user_id: str,
    workspace_id: str,
) -> "DocumentSectionRecord":
    metadata = dict(section.get("metadata") or {})
    metadata["secondary_types"] = list(section.get("secondary_types") or [])
    metadata["chunk_count"] = int(section.get("chunk_count", 0) or 0)
    return DocumentSectionRecord(
        id=_new_id(),
        user_id=user_id,
        workspace_id=workspace_id,
        document_id=document_id,
        section_type=str(section.get("section_type") or "unknown"),
        original_title=str(section.get("original_title") or "")[:255],
        ordinal=ordinal,
        page_start=_optional_int(section.get("page_start")),
        page_end=_optional_int(section.get("page_end")),
        char_start=int(section.get("char_start", 0) or 0),
        char_end=int(section.get("char_end", 0) or 0),
        text=str(section.get("text") or ""),
        language=str(section.get("language") or "unknown"),
        confidence=float(section.get("confidence", 0) or 0),
        metadata_json=_json(metadata),
        created_at=_utc_now(),
    )


def _section_dict(row: "DocumentSectionRecord") -> dict[str, Any]:
    metadata = _loads_dict(row.metadata_json)
    section_type = row.section_type
    return {
        "id": row.id,
        "document_id": row.document_id,
        "workspace_id": row.workspace_id,
        "type": section_type,
        "section_type": section_type,
        "original_title": row.original_title,
        "ordinal": row.ordinal,
        "page_start": row.page_start,
        "page_end": row.page_end,
        "char_start": row.char_start,
        "char_end": row.char_end,
        "text": row.text,
        "language": row.language,
        "confidence": row.confidence,
        "secondary_types": metadata.get("secondary_types", []),
        "chunk_count": metadata.get("chunk_count", 0),
        "metadata": metadata,
    }


def _workspace_condition(column, user_id: str, workspace_id: Optional[str]):
    if workspace_id:
        return column == workspace_id
    default_id = default_workspace_id(user_id)
    return or_(column == default_id, column.is_(None))


def _loads_list(value: str) -> list[str]:
    try:
        loaded = json.loads(value or "[]")
        return [str(item) for item in loaded] if isinstance(loaded, list) else []
    except json.JSONDecodeError:
        return []


def _loads_dict(value: str) -> dict[str, Any]:
    try:
        loaded = json.loads(value or "{}")
        return loaded if isinstance(loaded, dict) else {}
    except json.JSONDecodeError:
        return {}


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    return int(value)


def _new_id() -> str:
    # UUIDs keep repeated analysis runs independent from old rows.
    import uuid

    return uuid.uuid4().hex


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


medical_repository = MedicalRepository()
