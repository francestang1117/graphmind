"""API router composition.

Implemented:
- document upload/list/detail/delete routes
- in-memory knowledge graph routes for Module 4
- vector search routes for Module 5
"""

from fastapi import APIRouter
from app.api.endpoints import documents, graph, search

router = APIRouter()

router.include_router(documents.router, prefix="/documents", tags=["documents"])
router.include_router(graph.router, prefix="/graph", tags=["graph"])
router.include_router(search.router, prefix="/search", tags=["search"])
