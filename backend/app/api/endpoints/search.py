"""Search API over parsed document chunks."""

from typing import Literal, Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from app.api.endpoints.auth import UserRecord, current_user_or_dev
from app.api.endpoints.documents_with_markdown import get_cached_parse, parse_document_file
from app.core.rate_limit import search_limit
from app.services.document_service import document_service
from app.services.vector_store import VectorStore, vector_store


router = APIRouter()


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    limit: int = Field(default=8, ge=1, le=30)
    search_type: Literal["semantic", "hybrid"] = "hybrid"
    document: Optional[str] = None


@router.post("/")
@search_limit
async def search_documents(
    body: SearchRequest,
    user: UserRecord = Depends(current_user_or_dev),
    request: Request = None,
) -> dict:
    """Search all indexed chunks from current uploads.

    request is here for the rate limiter; body carries the actual search input.
    """
    store = rebuild_vector_index(user.id)
    if body.search_type == "semantic":
        raw_results = store.search(body.query, body.limit, body.document)
        results = [_api_result(item, percent=True) for item in raw_results]
    else:
        results = [_api_result(item) for item in store.hybrid_search(body.query, body.limit, body.document)]

    return {
        "query": body.query,
        "search_type": body.search_type,
        "results": results,
        "total": len(results),
    }


@router.get("/context")
@search_limit
async def search_context(
    q: str,
    limit: int = 5,
    user: UserRecord = Depends(current_user_or_dev),
    request: Request = None,
) -> dict:
    """Return stitched context for chat/RAG without letting one IP spam rebuilds."""
    store = rebuild_vector_index(user.id)
    return {"query": q, "context": store.get_context_for_qa(q, limit)}


@router.get("/stats")
async def search_stats(user: UserRecord = Depends(current_user_or_dev)) -> dict:
    """Return the current in-memory index size."""
    store = rebuild_vector_index(user.id)
    documents = {chunk.document for chunk in store.chunks.values()}
    return {"chunks": len(store.chunks), "documents": len(documents)}


def rebuild_vector_index(user_id: Optional[str] = None) -> VectorStore:
    """Build a fresh search index from stored parser chunks."""
    store = vector_store
    store.clear()
    for metadata in document_service.list_documents(user_id):
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
