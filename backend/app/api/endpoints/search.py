"""Search API over parsed document chunks."""

import logging
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field

from app.api.workspace_scope import resolve_workspace_id
from app.api.endpoints.auth import UserRecord, current_user_or_dev
from app.api.endpoints.documents_with_markdown import get_cached_parse, parse_document_file
from app.core.metrics import record_search
from app.core.rate_limit import search_limit
from app.services.document_service import document_service
from app.services.vector_store import VectorStore


router = APIRouter()
log = logging.getLogger(__name__)


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    limit: int = Field(default=8, ge=1, le=30)
    search_type: Literal["semantic", "hybrid"] = "hybrid"
    document: Optional[str] = None
    workspace_id: Optional[str] = None


@router.post("/")
@search_limit
async def search_documents(
    body: SearchRequest,
    user: UserRecord = Depends(current_user_or_dev),
    request: Request = None,
    response: Response = None,
) -> dict:
    """Search all indexed chunks from current uploads.

    request is here for the rate limiter; body carries the actual search input.
    """
    workspace_id = resolve_workspace_id(user.id, body.workspace_id)
    store = rebuild_vector_index(user.id, workspace_id)
    if body.search_type == "semantic":
        raw_results = store.search(body.query, body.limit, body.document)
        results = [_api_result(item, percent=True) for item in raw_results]
    else:
        results = [_api_result(item) for item in store.hybrid_search(body.query, body.limit, body.document)]

    # Empty-result searches are worth tracking; they usually mean bad indexing
    # or a query the current parser does not handle well.
    record_search(body.search_type, len(results))
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
    workspace_id: Optional[str] = None,
    user: UserRecord = Depends(current_user_or_dev),
    request: Request = None,
    response: Response = None,
) -> dict:
    """Return stitched context for chat/RAG without letting one IP spam rebuilds."""
    workspace_id = resolve_workspace_id(user.id, workspace_id)
    store = rebuild_vector_index(user.id, workspace_id)
    return {"query": q, "context": store.get_context_for_qa(q, limit)}


@router.get("/stats")
async def search_stats(
    workspace_id: Optional[str] = None,
    user: UserRecord = Depends(current_user_or_dev),
) -> dict:
    """Return the current in-memory index size."""
    workspace_id = resolve_workspace_id(user.id, workspace_id)
    store = rebuild_vector_index(user.id, workspace_id)
    documents = {chunk.document for chunk in store.chunks.values()}
    return {"chunks": len(store.chunks), "documents": len(documents)}


def rebuild_vector_index(
    user_id: Optional[str] = None,
    workspace_id: Optional[str] = None,
) -> VectorStore:
    """Build a fresh search index from stored parser chunks."""
    # A request gets its own index. A shared mutable store could briefly expose
    # another project's chunks while two searches are rebuilding at once.
    store = VectorStore()
    owner_id = user_id or "local-dev"
    documents = (
        document_service.list_documents(user_id, workspace_id=workspace_id)
        if workspace_id is not None
        else document_service.list_documents(user_id)
    )
    for metadata in documents:
        filename = metadata["filename"]
        original_name = metadata.get("original_filename", filename)
        parsed = (
            get_cached_parse(filename, owner_id, workspace_id)
            if workspace_id is not None
            else get_cached_parse(filename, owner_id)
        )
        if not parsed:
            try:
                arguments = {
                    "user_id": owner_id,
                    "document_id": metadata.get("document_id", ""),
                }
                if workspace_id is not None:
                    arguments["workspace_id"] = workspace_id
                parsed = parse_document_file(
                    filename,
                    metadata["file_path"],
                    original_name,
                    **arguments,
                )
            except (OSError, ValueError, RuntimeError) as exc:
                # Search should stay usable even if one stored file no longer
                # parses, but the skip should not be invisible.
                log.warning("Skipping %s while rebuilding search index: %s", original_name, exc)
                continue
        try:
            store.add_chunks(parsed.get("chunks", []), original_name)
        except (TypeError, ValueError) as exc:
            # Bad chunk shapes are parser bugs, not user mistakes. Log and keep
            # indexing the rest of the library.
            log.warning("Skipping search chunks for %s: %s", original_name, exc)
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
