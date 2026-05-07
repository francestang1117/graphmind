"""Database repository for parsed chunks and extracted entities."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Callable, Optional

from app.core.database import SessionLocal, db_enabled

try:
    from sqlalchemy import delete, select
    from app.models.persistence import DocumentRecord, ParsedChunkRecord, ParsedEntityRecord
except ImportError:  # pragma: no cover - only before DB deps are installed
    delete = None
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
            and select
            and DocumentRecord
            and ParsedChunkRecord
            and ParsedEntityRecord
        )

    def replace_for_document(
        self,
        filename: str,
        parsed: dict[str, Any],
        entities: list[Any],
    ) -> None:
        """Replace stored parse artifacts for one stored filename.

        Parsing is deterministic for the same file, so a full replace keeps the
        database honest when the parser improves or a file is reprocessed.
        """
        if not self.available():
            return

        with self.session_factory() as db:
            document = db.get(DocumentRecord, filename)
            user_id = document.user_id if document else "local-dev"

            # Keep only the latest parse for a document. This avoids stale
            # chunks hanging around after parser changes.
            db.execute(delete(ParsedChunkRecord).where(ParsedChunkRecord.document_id == filename))
            db.execute(delete(ParsedEntityRecord).where(ParsedEntityRecord.document_id == filename))

            for index, chunk in enumerate(parsed.get("chunks", [])):
                row = _chunk_record(filename, user_id, index, chunk)
                if row:
                    db.add(row)

            for entity in _dedupe_entities(entities):
                row = _entity_record(filename, user_id, entity)
                if row:
                    db.add(row)

            db.commit()

    def delete_for_document(self, filename: str) -> None:
        """Remove parse artifacts when the source document is deleted."""
        if not self.available():
            return

        with self.session_factory() as db:
            db.execute(delete(ParsedChunkRecord).where(ParsedChunkRecord.document_id == filename))
            db.execute(delete(ParsedEntityRecord).where(ParsedEntityRecord.document_id == filename))
            db.commit()

    def list_chunks(self, filename: str) -> list[dict[str, Any]]:
        if not self.available():
            return []

        with self.session_factory() as db:
            stmt = (
                select(ParsedChunkRecord)
                .where(ParsedChunkRecord.document_id == filename)
                .order_by(ParsedChunkRecord.chunk_index)
            )
            return [_chunk_to_dict(row) for row in db.scalars(stmt).all()]

    def list_entities(self, filename: str) -> list[dict[str, Any]]:
        if not self.available():
            return []

        with self.session_factory() as db:
            stmt = (
                select(ParsedEntityRecord)
                .where(ParsedEntityRecord.document_id == filename)
                .order_by(ParsedEntityRecord.confidence.desc(), ParsedEntityRecord.text)
            )
            return [_entity_to_dict(row) for row in db.scalars(stmt).all()]


def _chunk_record(
    document_id: str,
    user_id: str,
    index: int,
    chunk: Any,
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
    return ParsedChunkRecord(
        id=f"{document_id}:chunk:{index}",
        document_id=document_id,
        user_id=user_id,
        chunk_index=index,
        chunk_type=str(chunk.get("type") or chunk.get("chunk_type") or "text"),
        text=text,
        metadata_json=_json(metadata),
    )


def _entity_record(
    document_id: str,
    user_id: str,
    entity: Any,
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
    row_id = _row_id(document_id, normalized.lower(), label.lower())

    return ParsedEntityRecord(
        id=row_id,
        document_id=document_id,
        user_id=user_id,
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
        "chunk_index": row.chunk_index,
        "chunk_type": row.chunk_type,
        "text": row.text,
        "metadata": _loads(row.metadata_json),
    }


def _entity_to_dict(row: "ParsedEntityRecord") -> dict[str, Any]:
    return {
        "document_id": row.document_id,
        "user_id": row.user_id,
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


parsed_artifact_repository = ParsedArtifactRepository()
