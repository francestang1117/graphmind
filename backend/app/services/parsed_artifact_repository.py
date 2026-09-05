"""Database repository for parsed chunks and extracted entities."""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Callable, Optional

from app.core.database import SessionLocal, db_enabled
from app.core.workspace import default_workspace_id
from app.services.medical.repository import replace_analysis_in_session

log = logging.getLogger(__name__)

try:
    from sqlalchemy import delete, or_, select
    from app.models.persistence import DocumentRecord, ParsedChunkRecord, ParsedEntityRecord
except ImportError:  # pragma: no cover - only before DB deps are installed
    delete = None
    or_ = None
    select = None
    DocumentRecord = None  # type: ignore[assignment]
    ParsedChunkRecord = None  # type: ignore[assignment]
    ParsedEntityRecord = None  # type: ignore[assignment]


class ParsedArtifactRepository:
    """Stores parsed chunks/entities so later modules do not have to reparse files."""

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
            and ParsedChunkRecord
            and ParsedEntityRecord
        )

    def replace_for_document(
        self,
        identifier: str,
        parsed: dict[str, Any],
        entities: list[Any],
        *,
        user_id: str = "local-dev",
        workspace_id: Optional[str] = None,
    ) -> None:
        """Replace stored parse artifacts for one user's document.

        Parsing is deterministic for the same file, so a full replace keeps the
        database honest when the parser improves or a file is reprocessed.
        """
        if not self.available():
            return

        with self.session_factory() as db:
            document = _find_document(
                db,
                identifier,
                user_id,
                workspace_id=workspace_id,
                lock=True,
            )
            if not document:
                # Never create parse rows from an unverified filename. The
                # document row is the ownership check for everything below it.
                return
            if not self._replace_for_document_in_session(
                db,
                parsed,
                entities,
                user_id=user_id,
                document=document,
            ):
                db.rollback()
                return
            db.commit()

    def replace_parse_bundle(
        self,
        identifier: str,
        parsed: dict[str, Any],
        entities: list[Any],
        analysis: dict[str, Any],
        sections: list[dict[str, Any]],
        *,
        user_id: str = "local-dev",
        workspace_id: Optional[str] = None,
    ) -> bool:
        """Commit parser and medical rows as one database snapshot."""
        if not self.available():
            return False

        try:
            with self.session_factory() as db:
                document = _find_document(
                    db,
                    identifier,
                    user_id,
                    workspace_id=workspace_id,
                    lock=True,
                )
                if not document:
                    log.info("Skipping parse bundle for missing document %s", identifier)
                    return False

                if not self._replace_for_document_in_session(
                    db,
                    parsed,
                    entities,
                    user_id=user_id,
                    document=document,
                ):
                    db.rollback()
                    return False

                if not replace_analysis_in_session(
                    db,
                    identifier,
                    analysis,
                    sections,
                    user_id=user_id,
                    workspace_id=workspace_id,
                    document=document,
                ):
                    db.rollback()
                    return False

                db.commit()
                return True
        except Exception:
            # The session is closed without commit, so SQLAlchemy rolls back
            # all staged rows before the error reaches the parse task.
            log.exception("Could not commit parse bundle for %s", identifier)
            raise

    def _replace_for_document_in_session(
        self,
        db,
        parsed: dict[str, Any],
        entities: list[Any],
        *,
        user_id: str,
        document: Optional["DocumentRecord"] = None,
        identifier: str = "",
        workspace_id: Optional[str] = None,
    ) -> bool:
        """Stage chunks and entities without committing the session."""
        if document is None:
            document = _find_document(
                db,
                identifier,
                user_id,
                workspace_id=workspace_id,
                lock=True,
            )
        if not document:
            return False

        document_id = document.id
        document_workspace_id = document.workspace_id

        # Keep only the latest parse for a document. This avoids stale chunks
        # hanging around after parser changes.
        db.execute(
            delete(ParsedChunkRecord).where(
                ParsedChunkRecord.document_id == document_id,
                ParsedChunkRecord.user_id == user_id,
                _document_workspace_condition(
                    ParsedChunkRecord.workspace_id,
                    user_id,
                    document_workspace_id,
                ),
            )
        )
        db.execute(
            delete(ParsedEntityRecord).where(
                ParsedEntityRecord.document_id == document_id,
                ParsedEntityRecord.user_id == user_id,
                _document_workspace_condition(
                    ParsedEntityRecord.workspace_id,
                    user_id,
                    document_workspace_id,
                ),
            )
        )

        scope = document_workspace_id or default_workspace_id(user_id)
        for index, chunk in enumerate(parsed.get("chunks", [])):
            row = _chunk_record(
                document_id,
                user_id,
                index,
                chunk,
                workspace_id=scope,
            )
            if row:
                db.add(row)

        for entity in _dedupe_entities(entities):
            row = _entity_record(
                document_id,
                user_id,
                entity,
                workspace_id=scope,
            )
            if row:
                db.add(row)

        # with_for_update protects PostgreSQL. This conditional write also
        # keeps SQLite from committing after a delete won the race.
        return _document_is_active(
            db,
            document_id,
            user_id,
            workspace_id=document_workspace_id,
        )

    def delete_for_document(
        self,
        identifier: str,
        *,
        user_id: str = "local-dev",
        workspace_id: Optional[str] = None,
    ) -> None:
        """Remove parse artifacts when the source document is deleted."""
        if not self.available():
            return

        with self.session_factory() as db:
            # Cleanup must still find the row after the service sets deleted_at.
            document = _find_document(
                db,
                identifier,
                user_id,
                workspace_id=workspace_id,
                include_deleted=True,
                lock=True,
            )
            if not document:
                return
            document_id = document.id
            db.execute(
                delete(ParsedChunkRecord).where(
                    ParsedChunkRecord.document_id == document_id,
                    ParsedChunkRecord.user_id == user_id,
                    _document_workspace_condition(
                        ParsedChunkRecord.workspace_id,
                        user_id,
                        document.workspace_id,
                    ),
                )
            )
            db.execute(
                delete(ParsedEntityRecord).where(
                    ParsedEntityRecord.document_id == document_id,
                    ParsedEntityRecord.user_id == user_id,
                    _document_workspace_condition(
                        ParsedEntityRecord.workspace_id,
                        user_id,
                        document.workspace_id,
                    ),
                )
            )
            db.commit()

    def list_chunks(
        self,
        identifier: str,
        *,
        user_id: str = "local-dev",
        workspace_id: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        if not self.available():
            return []

        with self.session_factory() as db:
            document = _find_document(
                db,
                identifier,
                user_id,
                workspace_id=workspace_id,
            )
            if not document:
                return []
            stmt = (
                select(ParsedChunkRecord)
                .where(
                    ParsedChunkRecord.document_id == document.id,
                    ParsedChunkRecord.user_id == user_id,
                    _document_workspace_condition(
                        ParsedChunkRecord.workspace_id,
                        user_id,
                        document.workspace_id,
                    ),
                )
                .order_by(ParsedChunkRecord.chunk_index)
            )
            return [_chunk_to_dict(row) for row in db.scalars(stmt).all()]

    def list_entities(
        self,
        identifier: str,
        *,
        user_id: str = "local-dev",
        workspace_id: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        if not self.available():
            return []

        with self.session_factory() as db:
            document = _find_document(
                db,
                identifier,
                user_id,
                workspace_id=workspace_id,
            )
            if not document:
                return []
            stmt = (
                select(ParsedEntityRecord)
                .where(
                    ParsedEntityRecord.document_id == document.id,
                    ParsedEntityRecord.user_id == user_id,
                    _document_workspace_condition(
                        ParsedEntityRecord.workspace_id,
                        user_id,
                        document.workspace_id,
                    ),
                )
                .order_by(ParsedEntityRecord.confidence.desc(), ParsedEntityRecord.text)
            )
            return [_entity_to_dict(row) for row in db.scalars(stmt).all()]


def _find_document(
    db,
    identifier: str,
    user_id: str,
    *,
    workspace_id: Optional[str] = None,
    include_deleted: bool = False,
    lock: bool = False,
) -> Optional["DocumentRecord"]:
    """Resolve one document without crossing a user's workspace."""
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


def _document_is_active(
    db,
    document_id: str,
    user_id: str,
    *,
    workspace_id: Optional[str] = None,
) -> bool:
    """Check the delete marker at the point where derived rows are committed."""
    return (
        db.scalars(
            select(DocumentRecord.id).where(
                DocumentRecord.id == document_id,
                DocumentRecord.user_id == user_id,
                _workspace_condition(DocumentRecord.workspace_id, user_id, workspace_id),
                DocumentRecord.deleted_at.is_(None),
            )
        ).first()
        is not None
    )


def _chunk_record(
    document_id: str,
    user_id: str,
    index: int,
    chunk: Any,
    *,
    workspace_id: Optional[str] = None,
) -> Optional["ParsedChunkRecord"]:
    """Turn one parser chunk into a database row, skipping empty output."""
    if not isinstance(chunk, dict):
        return None
    text = str(chunk.get("text", "")).strip()
    if not text:
        return None

    # Everything except the actual text is kept as metadata so different
    # parsers can add page/section/language details without schema churn.
    metadata = {key: value for key, value in chunk.items() if key != "text"}
    scope = workspace_id or default_workspace_id(user_id)
    return ParsedChunkRecord(
        id=f"{user_id}:{scope}:{document_id}:chunk:{index}",
        document_id=document_id,
        user_id=user_id,
        workspace_id=scope,
        chunk_index=index,
        chunk_type=str(chunk.get("type") or chunk.get("chunk_type") or "text"),
        text=text,
        metadata_json=_json(metadata),
    )


def _entity_record(
    document_id: str,
    user_id: str,
    entity: Any,
    *,
    workspace_id: Optional[str] = None,
) -> Optional["ParsedEntityRecord"]:
    """Turn one extracted entity into a database row."""
    data = _entity_dict(entity)
    text = str(data.get("text", "")).strip()
    if not text:
        return None

    label = str(data.get("label") or data.get("type") or "ENTITY").upper()
    normalized = str(data.get("normalized") or text).strip()
    source = str(data.get("source") or "parser")
    confidence = float(data.get("confidence", 1.0) or 0)
    context = str(data.get("context") or "")
    # Stable ids make replace operations predictable across SQLite/Postgres.
    scope = workspace_id or default_workspace_id(user_id)
    row_id = _row_id(user_id, scope, document_id, normalized.lower(), label.lower())

    return ParsedEntityRecord(
        id=row_id,
        document_id=document_id,
        user_id=user_id,
        workspace_id=scope,
        text=text[:255],
        normalized=normalized[:255],
        label=label[:80],
        source=source[:80],
        confidence=confidence,
        context=context,
        metadata_json=_json({k: v for k, v in data.items() if k not in {"text", "label", "type", "normalized", "source", "confidence", "context"}}),
    )


def _entity_dict(entity: Any) -> dict[str, Any]:
    if isinstance(entity, dict):
        return entity
    if hasattr(entity, "to_dict"):
        return entity.to_dict()
    if hasattr(entity, "__dict__"):
        return dict(entity.__dict__)
    return {}


def _dedupe_entities(entities: list[Any]) -> list[Any]:
    """Keep one entity per normalized name/type pair for a document."""
    seen = set()
    result = []
    for entity in entities:
        data = _entity_dict(entity)
        text = str(data.get("normalized") or data.get("text") or "").strip().lower()
        label = str(data.get("label") or data.get("type") or "ENTITY").upper()
        key = (text, label)
        if not text or key in seen:
            continue
        seen.add(key)
        result.append(entity)
    return result


def _chunk_to_dict(row: "ParsedChunkRecord") -> dict[str, Any]:
    return {
        "document_id": row.document_id,
        "user_id": row.user_id,
        "workspace_id": row.workspace_id,
        "chunk_index": row.chunk_index,
        "chunk_type": row.chunk_type,
        "text": row.text,
        "metadata": _loads(row.metadata_json),
    }


def _entity_to_dict(row: "ParsedEntityRecord") -> dict[str, Any]:
    return {
        "document_id": row.document_id,
        "user_id": row.user_id,
        "workspace_id": row.workspace_id,
        "text": row.text,
        "normalized": row.normalized,
        "label": row.label,
        "source": row.source,
        "confidence": row.confidence,
        "context": row.context,
        "metadata": _loads(row.metadata_json),
    }


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _loads(value: str) -> dict[str, Any]:
    try:
        loaded = json.loads(value or "{}")
        return loaded if isinstance(loaded, dict) else {}
    except json.JSONDecodeError:
        return {}


def _row_id(*parts: str) -> str:
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _workspace_condition(column, user_id: str, workspace_id: Optional[str]):
    """Keep old NULL rows visible only in the user's default project."""
    if workspace_id:
        return column == workspace_id
    default_id = default_workspace_id(user_id)
    return or_(column == default_id, column.is_(None))


def _document_workspace_condition(column, user_id: str, document_workspace_id: Optional[str]):
    """Match derived rows written before workspace columns were introduced."""
    if document_workspace_id:
        return column == document_workspace_id
    default_id = default_workspace_id(user_id)
    return or_(column == default_id, column.is_(None))


parsed_artifact_repository = ParsedArtifactRepository()
