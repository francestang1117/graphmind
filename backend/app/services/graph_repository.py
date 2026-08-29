"""Persistence for the knowledge graph tables."""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Callable

from app.core.database import SessionLocal, db_enabled

log = logging.getLogger(__name__)

try:
    from sqlalchemy import delete, select
    from sqlalchemy.exc import SQLAlchemyError
    from app.models.persistence import GraphEdgeRecord, GraphNodeRecord, utc_now
except ImportError:  # pragma: no cover - only before DB deps are installed
    delete = None
    select = None
    SQLAlchemyError = Exception
    GraphEdgeRecord = None  # type: ignore[assignment]
    GraphNodeRecord = None  # type: ignore[assignment]
    utc_now = None  # type: ignore[assignment]


class GraphRepository:
    """Stores graph nodes/edges without replacing the in-memory graph yet."""

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
            and GraphNodeRecord
            and GraphEdgeRecord
        )

    def replace_document_graph(
        self,
        *,
        user_id: str,
        document_id: str,
        graph: dict[str, Any],
    ) -> None:
        """Replace the persisted graph slice created by one document."""
        if not self.available():
            return

        try:
            with self.session_factory() as db:
                # Reindexing should leave one clean slice per document, not a
                # pile of stale edges from older parser/entity rules.
                self._remove_document_slice(db, user_id, document_id)
                # If a node is deleted and re-added in the same transaction,
                # SQLite/SQLAlchemy can still remember the old identity until
                # the delete is flushed.
                db.flush()

                for node in graph.get("nodes", []):
                    self._upsert_node(db, user_id, document_id, node)

                for edge in graph.get("edges", []):
                    db.add(_edge_record(user_id, document_id, edge))

                db.commit()
        except (SQLAlchemyError, OSError, RuntimeError) as exc:
            log.warning("Could not persist graph slice for %s: %s", document_id, exc)

    def delete_for_document(self, document_id: str, user_id: str | None = None) -> None:
        """Remove graph rows that came from one document."""
        if not self.available():
            return

        try:
            with self.session_factory() as db:
                self._remove_document_slice(db, user_id, document_id)
                db.commit()
        except (SQLAlchemyError, OSError, RuntimeError) as exc:
            log.warning("Could not delete graph slice for %s: %s", document_id, exc)

    def load_graph(self, user_id: str | None = None) -> dict[str, Any]:
        """Return persisted graph data in the same detailed shape as the builder."""
        if not self.available():
            return {"nodes": [], "edges": []}

        try:
            with self.session_factory() as db:
                node_stmt = select(GraphNodeRecord)
                edge_stmt = select(GraphEdgeRecord)
                if user_id:
                    node_stmt = node_stmt.where(GraphNodeRecord.user_id == user_id)
                    edge_stmt = edge_stmt.where(GraphEdgeRecord.user_id == user_id)

                nodes = [_node_to_dict(row) for row in db.scalars(node_stmt).all()]
                edges = _aggregate_edges(
                    [_edge_to_dict(row) for row in db.scalars(edge_stmt).all()]
                )
                return {"nodes": nodes, "edges": edges}
        except (SQLAlchemyError, OSError, RuntimeError) as exc:
            log.warning("Could not load persisted graph: %s", exc)
            return {"nodes": [], "edges": []}

    def has_graph(self, user_id: str | None = None) -> bool:
        if not self.available():
            return False

        try:
            with self.session_factory() as db:
                stmt = select(GraphNodeRecord.id)
                if user_id:
                    stmt = stmt.where(GraphNodeRecord.user_id == user_id)
                return db.scalars(stmt).first() is not None
        except (SQLAlchemyError, OSError, RuntimeError) as exc:
            log.warning("Could not check persisted graph: %s", exc)
            return False

    def _remove_document_slice(self, db, user_id: str | None, document_id: str) -> None:
        # Edges belong to one document slice, so they can be removed directly.
        edge_stmt = delete(GraphEdgeRecord).where(GraphEdgeRecord.source_document_id == document_id)
        node_stmt = select(GraphNodeRecord)
        if user_id:
            edge_stmt = edge_stmt.where(GraphEdgeRecord.user_id == user_id)
            node_stmt = node_stmt.where(GraphNodeRecord.user_id == user_id)

        db.execute(edge_stmt)
        for node in db.scalars(node_stmt).all():
            current_source_ids = _loads_list(node.source_document_ids_json)
            if document_id not in current_source_ids:
                continue
            source_ids = [item for item in current_source_ids if item != document_id]
            if not source_ids:
                # Only remove the node when this document was its last source.
                # Shared concepts like Python should survive other file deletes.
                db.delete(node)
                continue
            node.source_document_ids_json = _json(source_ids)
            node.updated_at = utc_now()

    def _upsert_node(
        self,
        db,
        user_id: str,
        document_id: str,
        node: dict[str, Any],
    ) -> None:
        node_id = str(node.get("id") or "")
        if not node_id:
            return

        row_id = _row_id(user_id, node_id)
        record = db.get(GraphNodeRecord, row_id)
        if not record:
            db.add(_node_record(user_id, document_id, node))
            return

        # Same entity, new source. Keep the strongest confidence and merge the
        # source lists so graph detail views can explain where a node came from.
        sources = _merge_unique(_loads_list(record.sources_json), node.get("sources", []))
        source_ids = _merge_unique(_loads_list(record.source_document_ids_json), [document_id])
        record.label = str(node.get("label") or record.label)[:255]
        record.node_type = str(node.get("type") or record.node_type).upper()[:80]
        record.confidence = max(float(record.confidence or 0), float(node.get("confidence", 1.0) or 0))
        record.sources_json = _json(sources)
        record.source_document_ids_json = _json(source_ids)
        record.properties_json = _json({**_loads_dict(record.properties_json), **(node.get("properties") or {})})
        record.updated_at = utc_now()


def _node_record(user_id: str, document_id: str, node: dict[str, Any]) -> "GraphNodeRecord":
    node_id = str(node.get("id") or "")
    return GraphNodeRecord(
        id=_row_id(user_id, node_id),
        user_id=user_id,
        node_id=node_id,
        label=str(node.get("label") or "")[:255],
        node_type=str(node.get("type") or "ENTITY").upper()[:80],
        confidence=float(node.get("confidence", 1.0) or 0),
        sources_json=_json(node.get("sources", [])),
        source_document_ids_json=_json([document_id]),
        properties_json=_json(node.get("properties", {})),
    )


def _edge_record(user_id: str, document_id: str, edge: dict[str, Any]) -> "GraphEdgeRecord":
    source = str(edge.get("source") or "")
    target = str(edge.get("target") or "")
    relation = str(edge.get("type") or "RELATED_TO").upper()
    # Include document_id in the key because the same relation can be supported
    # by more than one file. Later we can aggregate those rows for weight.
    return GraphEdgeRecord(
        id=_row_id(user_id, source, target, relation, document_id),
        user_id=user_id,
        source_node_id=source,
        target_node_id=target,
        relation_type=relation[:80],
        source_document_id=document_id,
        confidence=float(edge.get("confidence", 1.0) or 0),
        weight=int(edge.get("weight", 1) or 1),
        sources_json=_json(edge.get("sources", [])),
    )


def _node_to_dict(row: "GraphNodeRecord") -> dict[str, Any]:
    return {
        "id": row.node_id,
        "label": row.label,
        "type": row.node_type,
        "sources": _loads_list(row.sources_json),
        "confidence": row.confidence,
        "properties": _loads_dict(row.properties_json),
        "created_at": row.created_at.isoformat() if row.created_at else "",
        "updated_at": row.updated_at.isoformat() if row.updated_at else "",
    }


def _edge_to_dict(row: "GraphEdgeRecord") -> dict[str, Any]:
    return {
        "source": row.source_node_id,
        "target": row.target_node_id,
        "type": row.relation_type,
        "confidence": row.confidence,
        "weight": row.weight,
        "sources": _loads_list(row.sources_json),
        "created_at": row.created_at.isoformat() if row.created_at else "",
        "updated_at": row.updated_at.isoformat() if row.updated_at else "",
    }


def _aggregate_edges(edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Combine relation evidence stored by separate document slices."""
    grouped: dict[tuple[str, str, str], dict[str, Any]] = {}
    for edge in edges:
        key = (edge["source"], edge["target"], edge["type"])
        current = grouped.get(key)
        if not current:
            grouped[key] = {**edge, "sources": list(edge.get("sources") or [])}
            continue

        current["weight"] = int(current.get("weight", 1)) + int(edge.get("weight", 1))
        current["confidence"] = max(
            float(current.get("confidence", 0)),
            float(edge.get("confidence", 0)),
        )
        current["sources"] = _merge_unique(current.get("sources", []), edge.get("sources", []))
        if edge.get("updated_at", "") > current.get("updated_at", ""):
            current["updated_at"] = edge["updated_at"]
    return list(grouped.values())


def _merge_unique(left: list[Any], right: Any) -> list[str]:
    result = [str(item) for item in left if str(item)]
    incoming = right if isinstance(right, list) else [right]
    for item in incoming:
        text = str(item)
        if text and text not in result:
            result.append(text)
    return result


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


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


def _row_id(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


graph_repository = GraphRepository()
