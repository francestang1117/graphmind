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

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.api.endpoints.auth import UserRecord, current_user_or_dev
from app.api.endpoints.documents_with_markdown import get_cached_parse, parse_document_file
from app.core.rate_limit import graph_read_limit
from app.services.document_service import document_service
from app.services.entity_extractor import entity_extractor
from app.services.graph_builder_enhanced import KnowledgeGraph, knowledge_graph


router = APIRouter()


@router.get("/")
@graph_read_limit
async def get_graph(
    user: UserRecord = Depends(current_user_or_dev),
    request: Request = None,
) -> dict:
    """Return a graph built from all currently uploaded documents.

    Graph reads are cheaper than uploads/chat, but they still rebuild the
    in-memory graph today, so they get a gentler limit instead of none.
    """
    graph = rebuild_graph_from_documents(user.id)
    return graph.export_for_visualization()


@router.get("/stats")
@graph_read_limit
async def get_graph_stats(
    user: UserRecord = Depends(current_user_or_dev),
    request: Request = None,
) -> dict:
    """Return graph counters under the same read limit as the graph canvas."""
    graph = rebuild_graph_from_documents(user.id)
    return graph.get_stats()


@router.get("/nodes/{node_id}")
@graph_read_limit
async def get_node(
    node_id: str,
    user: UserRecord = Depends(current_user_or_dev),
    request: Request = None,
) -> dict:
    """Return one node plus its directly connected neighborhood."""
    graph = rebuild_graph_from_documents(user.id)
    node = graph.get_node(node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")

    neighbors = graph.get_neighbors(node_id)
    return {"node": node, "neighbors": neighbors, "neighbor_count": len(neighbors)}


@router.get("/search")
@graph_read_limit
async def search_nodes(
    q: str = Query("", description="Label text to search for"),
    node_type: Optional[str] = Query(None, description="Optional node type filter"),
    limit: int = Query(10, ge=1, le=50),
    user: UserRecord = Depends(current_user_or_dev),
    request: Request = None,
) -> dict:
    """Search graph nodes by label."""
    graph = rebuild_graph_from_documents(user.id)
    return {"results": graph.search_nodes(q, node_type=node_type, limit=limit)}


@router.get("/debug")
@graph_read_limit
async def graph_debug(
    user: UserRecord = Depends(current_user_or_dev),
    request: Request = None,
) -> dict:
    """Return full node and edge metadata for development checks."""
    graph = rebuild_graph_from_documents(user.id)
    return {**graph.export_detailed(), "stats": graph.get_stats()}


def rebuild_graph_from_documents(user_id: Optional[str] = None) -> KnowledgeGraph:
    """Build a fresh in-memory graph from stored files and cached parses."""
    graph = knowledge_graph
    graph.clear()

    for metadata in document_service.list_documents(user_id):
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
