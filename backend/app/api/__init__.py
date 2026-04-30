"""API router composition.

Implemented:
- document upload/list/detail/delete routes
- in-memory knowledge graph routes for Module 4
"""

from fastapi import APIRouter
from app.api.endpoints import documents, graph

router = APIRouter()

router.include_router(documents.router, prefix="/documents", tags=["documents"])
router.include_router(graph.router, prefix="/graph", tags=["graph"])
