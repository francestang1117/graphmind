"""Knowledge graph builder for Module 4.

Implemented:
- document, entity, and relation nodes/edges
- content merge by normalized entity id
- document-to-entity mention edges
- relation edges from Module 3 entity extraction
- simple node search, neighbor lookup, and graph stats
- frontend-ready visualization export

This module deliberately stays light for now. It keeps the graph in memory and
does not require NetworkX or Neo4j yet, which makes the current upload -> parse
-> entity -> graph flow easy to run locally. Persistent graph storage can be
added later without changing the API shape too much.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import re
from typing import Any, Iterable, Optional


# The main canvas should show knowledge-bearing nodes. More mechanical details
# stay available in /graph/debug for development and later filtering controls.
VISUAL_HIDDEN_NODE_TYPES = {"VERSION", "RESOURCE", "REPOSITORY", "CSV_VALUE"}
VISUAL_HIDDEN_EDGE_TYPES = {"MENTIONS_WITH"}


@dataclass
class GraphNode:
    id: str
    label: str
    type: str
    sources: list[str] = field(default_factory=list)
    confidence: float = 1.0
    properties: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: _now())
    updated_at: str = field(default_factory=lambda: _now())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class GraphEdge:
    source: str
    target: str
    type: str
    confidence: float = 1.0
    weight: int = 1
    sources: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: _now())
    updated_at: str = field(default_factory=lambda: _now())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class KnowledgeGraph:
    """Small in-memory graph used by the current backend and frontend."""

    def __init__(self) -> None:
        self.nodes: dict[str, GraphNode] = {}
        self.edges: dict[tuple[str, str, str], GraphEdge] = {}
        self.node_index: dict[str, str] = {}

    def clear(self) -> None:
        """Reset the graph, mainly used by tests and rebuild-on-read endpoints."""
        self.nodes.clear()
        self.edges.clear()
        self.node_index.clear()

    def add_document(
        self,
        document_name: str,
        entities: Iterable[Any],
        relations: Iterable[Any] = (),
        document_id: Optional[str] = None,
    ) -> str:
        """Add one parsed document plus extracted entities and relation hints."""
        doc_node_id = self.add_node(
            label=document_name,
            node_type="DOCUMENT",
            source_document=document_name,
            node_id=document_id or self._node_id(document_name, "DOCUMENT"),
            properties={"filename": document_name},
        )

        entity_map: dict[str, str] = {}
        for entity in entities:
            text = _get(entity, "text", "")
            label = _get(entity, "label", _get(entity, "type", "ENTITY"))
            if not text:
                continue

            normalized = _get(entity, "normalized", "") or _normalize(text)
            confidence = float(_get(entity, "confidence", 1.0) or 1.0)
            source = _get(entity, "source", "entity_extractor")
            node_id = self.add_node(
                label=text,
                node_type=str(label).upper(),
                source_document=document_name,
                confidence=confidence,
                properties={
                    "normalized": normalized,
                    "source_type": source,
                    "context": _get(entity, "context", ""),
                },
            )
            entity_map[normalized] = node_id
            entity_map[text] = node_id
            entity_map[text.lower()] = node_id

            # Direction is document -> entity so the graph reads naturally in
            # the frontend: this document mentions these concepts.
            self.add_edge(doc_node_id, node_id, "MENTIONS", confidence=confidence, source_document=document_name)

        for relation in relations:
            source_id = self._resolve_relation_node(relation, "source", entity_map)
            target_id = self._resolve_relation_node(relation, "target", entity_map)
            relation_type = str(_get(relation, "relation", "RELATED_TO")).upper()
            if source_id and target_id and source_id != target_id:
                self.add_edge(
                    source_id,
                    target_id,
                    relation_type,
                    confidence=float(_get(relation, "confidence", 1.0) or 1.0),
                    source_document=document_name,
                )

        return doc_node_id

    def add_node(
        self,
        label: str,
        node_type: str,
        source_document: str,
        confidence: float = 1.0,
        properties: Optional[dict[str, Any]] = None,
        node_id: Optional[str] = None,
    ) -> str:
        """Create or update a node, merging repeated entities by normalized id."""
        node_type = node_type.upper()
        properties = properties or {}
        identity = str(properties.get("normalized") or label)
        node_id = node_id or self._node_id(identity, node_type)

        if node_id in self.nodes:
            node = self.nodes[node_id]
            if source_document and source_document not in node.sources:
                node.sources.append(source_document)
            node.confidence = max(node.confidence, confidence)
            node.properties.update({key: value for key, value in properties.items() if value not in ("", None)})
            node.updated_at = _now()
        else:
            node = GraphNode(
                id=node_id,
                label=label,
                type=node_type,
                sources=[source_document] if source_document else [],
                confidence=confidence,
                properties={key: value for key, value in properties.items() if value not in ("", None)},
            )
            self.nodes[node_id] = node

        self.node_index[_normalize(label)] = node_id
        return node_id

    def add_edge(
        self,
        source_id: str,
        target_id: str,
        relation_type: str,
        confidence: float = 1.0,
        source_document: str = "",
    ) -> None:
        """Create or strengthen an edge between two existing nodes."""
        if source_id not in self.nodes or target_id not in self.nodes:
            return

        relation_type = relation_type.upper()
        key = (source_id, target_id, relation_type)
        if key in self.edges:
            edge = self.edges[key]
            edge.weight += 1
            edge.confidence = max(edge.confidence, confidence)
            if source_document and source_document not in edge.sources:
                edge.sources.append(source_document)
            edge.updated_at = _now()
            return

        self.edges[key] = GraphEdge(
            source=source_id,
            target=target_id,
            type=relation_type,
            confidence=confidence,
            sources=[source_document] if source_document else [],
        )

    def get_node(self, node_id: str) -> Optional[dict[str, Any]]:
        node = self.nodes.get(node_id)
        return node.to_dict() if node else None

    def get_neighbors(
        self,
        node_id: str,
        relation_type: Optional[str] = None,
        direction: str = "both",
    ) -> list[dict[str, Any]]:
        """Return directly connected nodes and the edges that connect them."""
        if node_id not in self.nodes:
            return []

        relation_filter = relation_type.upper() if relation_type else None
        neighbors = []
        for edge in self.edges.values():
            if relation_filter and edge.type != relation_filter:
                continue
            if direction in {"out", "both"} and edge.source == node_id:
                neighbors.append({"node": self.get_node(edge.target), "relation": edge.to_dict()})
            if direction in {"in", "both"} and edge.target == node_id:
                neighbors.append({"node": self.get_node(edge.source), "relation": edge.to_dict()})
        return neighbors

    def search_nodes(
        self,
        query: str,
        node_type: Optional[str] = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Simple label search used by early graph UI/API work."""
        needle = query.strip().lower()
        type_filter = node_type.upper() if node_type else None
        matches = []
        for node in self.nodes.values():
            if type_filter and node.type != type_filter:
                continue
            if not needle or needle in node.label.lower():
                matches.append(node.to_dict())
            if len(matches) >= limit:
                break
        return matches

    def get_stats(self) -> dict[str, Any]:
        """Return graph counts that can be shown directly in the UI."""
        node_types = Counter(node.type for node in self.nodes.values())
        edge_types = Counter(edge.type for edge in self.edges.values())
        node_count = len(self.nodes)
        possible_edges = node_count * (node_count - 1)
        density = len(self.edges) / possible_edges if possible_edges else 0

        return {
            "total_nodes": node_count,
            "total_edges": len(self.edges),
            "node_types": dict(node_types),
            "edge_types": dict(edge_types),
            "density": round(density, 4),
        }

    def export_for_visualization(self) -> dict[str, Any]:
        """Return the compact shape expected by the React canvas graph.

        The detailed graph keeps all extracted signals, including versions and
        weak co-mentions. The visual graph filters those out so the UI explains
        the knowledge base instead of turning dependency metadata into static.
        """
        degree = Counter()
        entity_keys = {
            _visual_identity(node.label)
            for node in self.nodes.values()
            if node.type != "DOCUMENT"
        }
        visible_nodes = {
            node_id: node
            for node_id, node in self.nodes.items()
            if self._is_visual_node(node, entity_keys)
        }
        visible_edges = [
            edge
            for edge in self.edges.values()
            if (
                edge.type not in VISUAL_HIDDEN_EDGE_TYPES
                and edge.source in visible_nodes
                and edge.target in visible_nodes
            )
        ]

        for edge in visible_edges:
            degree[edge.source] += edge.weight
            degree[edge.target] += edge.weight

        return {
            "nodes": [
                {
                    "id": node.id,
                    "label": node.label,
                    "type": node.type,
                    "size": self._visual_size(node, degree[node.id]),
                }
                for node in visible_nodes.values()
            ],
            # The frontend currently renders a tuple list. Detailed edge data
            # remains available through export_detailed().
            "edges": [(edge.source, edge.target) for edge in visible_edges],
            "edge_details": [
                {
                    "source": edge.source,
                    "target": edge.target,
                    "type": edge.type,
                    "weight": edge.weight,
                }
                for edge in visible_edges
            ],
            "stats": _stats_for(visible_nodes.values(), visible_edges),
        }

    def export_detailed(self) -> dict[str, Any]:
        """Return full node/edge metadata for API consumers and debugging."""
        return {
            "nodes": [node.to_dict() for node in self.nodes.values()],
            "edges": [edge.to_dict() for edge in self.edges.values()],
        }

    def _resolve_relation_node(
        self,
        relation: Any,
        field_name: str,
        entity_map: dict[str, str],
    ) -> Optional[str]:
        value = _get(relation, field_name, "")
        return entity_map.get(value) or entity_map.get(str(value).lower()) or entity_map.get(_normalize(str(value)))

    def _node_id(self, label: str, node_type: str) -> str:
        key = f"{node_type}:{_normalize(label)}"
        digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]
        prefix = "doc" if node_type == "DOCUMENT" else "ent"
        return f"{prefix}_{digest}"

    def _is_visual_node(self, node: GraphNode, entity_keys: set[str]) -> bool:
        if node.type in VISUAL_HIDDEN_NODE_TYPES:
            return False
        label = node.label.strip()
        if node.type in {"DEPENDENCY", "LIBRARY"} and _looks_like_internal_path(label):
            return False
        if node.type == "DOCUMENT" and _visual_identity(label) in entity_keys:
            return False
        return True

    def _visual_size(self, node: GraphNode, degree: int) -> float:
        if node.type == "DOCUMENT":
            return min(10.5, 6 + degree * 0.65)
        return min(19, 8 + degree * 1.15 + node.confidence * 1.5)


def _get(item: Any, key: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


def _normalize(value: str) -> str:
    clean = re.sub(r"\s+", " ", value.strip().lower())
    return clean


def _looks_like_internal_path(value: str) -> bool:
    return value.startswith((".", "/", "../")) or "/_" in value


def _visual_identity(value: str) -> str:
    stem = Path(value).stem if "." in Path(value).name else value
    return re.sub(r"[^a-z0-9]+", "", stem.lower().lstrip("_"))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stats_for(nodes: Iterable[GraphNode], edges: Iterable[GraphEdge]) -> dict[str, Any]:
    node_list = list(nodes)
    edge_list = list(edges)
    node_count = len(node_list)
    possible_edges = node_count * (node_count - 1)
    density = len(edge_list) / possible_edges if possible_edges else 0
    return {
        "total_nodes": node_count,
        "total_edges": len(edge_list),
        "node_types": dict(Counter(node.type for node in node_list)),
        "edge_types": dict(Counter(edge.type for edge in edge_list)),
        "density": round(density, 4),
    }


knowledge_graph = KnowledgeGraph()
