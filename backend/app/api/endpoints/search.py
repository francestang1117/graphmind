"""Search endpoints for Module 5.

Implemented:
- rebuild an in-memory vector index from uploaded documents
- semantic-ish vector search over parser chunks
- hybrid keyword + vector scoring
- context endpoint for future chat/RAG
"""

from typing import Literal, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.api.endpoints.documents_with_markdown import get_cached_parse, parse_document_file
from app.services.document_service import document_service
from app.services.vector_store import VectorStore, vector_store


router = APIRouter()


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    limit: int = Field(default=8, ge=1, le=30)
    search_type: Literal["semantic", "hybrid"] = "hybrid"
    document: Optional[str] = None


@router.post("/")
async def search_documents(request: SearchRequest) -> dict:
    """Search all indexed chunks from current uploads."""
    store = rebuild_vector_index()
    if request.search_type == "semantic":
        raw_results = store.search(request.query, request.limit, request.document)
        results = [_api_result(item, percent=True) for item in raw_results]
    else:
        results = [_api_result(item) for item in store.hybrid_search(request.query, request.limit, request.document)]

    return {
        "query": request.query,
        "search_type": request.search_type,
        "results": results,
        "total": len(results),
    }


@router.get("/context")
async def search_context(q: str, limit: int = 5) -> dict:
    """Return stitched context for a future chat/RAG module."""
    store = rebuild_vector_index()
    return {"query": q, "context": store.get_context_for_qa(q, limit)}


@router.get("/stats")
async def search_stats() -> dict:
    """Return the current in-memory index size."""
    store = rebuild_vector_index()
    documents = {chunk.document for chunk in store.chunks.values()}
    return {"chunks": len(store.chunks), "documents": len(documents)}


def rebuild_vector_index() -> VectorStore:
    """Build a fresh search index from stored parser chunks."""
    store = vector_store
    store.clear()
    for metadata in document_service.list_documents():
        filename = metadata["filename"]
        original_name = metadata.get("original_filename", filename)
        parsed = get_cached_parse(filename)
        if not parsed:
            try:
                parsed = parse_document_file(filename, metadata["file_path"], original_name)
            except Exception:
                continue
        store.add_chunks(parsed.get("chunks", []), original_name)
    return store


def _api_result(item: dict, percent: bool = False) -> dict:
    score = item["score"] * 100 if percent else item["score"]
    return {
        "title": item["title"],
        "type": item["type"],
        "score": round(score, 1),
        "excerpt": item["excerpt"],
        "source": item["source"],
        "tags": item.get("tags", [item.get("chunk_type", "text")]),
    }
