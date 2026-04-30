"""Knowledge graph endpoints.

Implemented:
- rebuild the in-memory graph from uploaded documents
- return frontend-ready graph data
- graph statistics
- node detail and neighbor lookup
- basic node search

The graph is rebuilt from current stored files for now. That keeps Module 4
honest while persistence is still planned: deleting or uploading documents is
reflected the next time the graph endpoint is requested.
"""

from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app.api.endpoints.documents_with_markdown import get_cached_parse, parse_document_file
from app.services.document_service import document_service
from app.services.entity_extractor import entity_extractor
from app.services.graph_builder_enhanced import KnowledgeGraph, knowledge_graph


router = APIRouter()


@router.get("/")
async def get_graph() -> dict:
    """Return a graph built from all currently uploaded documents."""
    graph = rebuild_graph_from_documents()
    return graph.export_for_visualization()


@router.get("/stats")
async def get_graph_stats() -> dict:
    """Return graph counters without duplicating frontend demo values."""
    graph = rebuild_graph_from_documents()
    return graph.get_stats()


@router.get("/nodes/{node_id}")
async def get_node(node_id: str) -> dict:
    """Return one node plus its directly connected neighborhood."""
    graph = rebuild_graph_from_documents()
    node = graph.get_node(node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")

    neighbors = graph.get_neighbors(node_id)
    return {"node": node, "neighbors": neighbors, "neighbor_count": len(neighbors)}


@router.get("/search")
async def search_nodes(
    q: str = Query("", description="Label text to search for"),
    node_type: Optional[str] = Query(None, description="Optional node type filter"),
    limit: int = Query(10, ge=1, le=50),
) -> dict:
    """Search graph nodes by label."""
    graph = rebuild_graph_from_documents()
    return {"results": graph.search_nodes(q, node_type=node_type, limit=limit)}


@router.get("/debug")
async def graph_debug() -> dict:
    """Return full node and edge metadata for development checks."""
    graph = rebuild_graph_from_documents()
    return {**graph.export_detailed(), "stats": graph.get_stats()}


def rebuild_graph_from_documents() -> KnowledgeGraph:
    """Build a fresh in-memory graph from stored files and cached parses."""
    graph = knowledge_graph
    graph.clear()

    for metadata in document_service.list_documents():
        filename = metadata["filename"]
        original_name = metadata.get("original_filename", filename)
        parsed = get_cached_parse(filename)
        if not parsed:
            try:
                parsed = parse_document_file(filename, metadata["file_path"], original_name)
            except Exception:
                # A single bad document should not make the whole graph panel fail.
                continue

        entities = entity_extractor.extract_from_parsed_document(parsed)
        relations = entity_extractor.extract_relations(entities, parsed.get("content", ""))
        graph.add_document(original_name, entities, relations, document_id=f"doc:{filename}")

    return graph
