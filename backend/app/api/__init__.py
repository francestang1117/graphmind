"""API router composition.

Implemented:
- document upload/list/detail/delete routes
- in-memory knowledge graph routes for Module 4
- vector search routes for Module 5
- AI chat routes for Module 7
- JWT auth routes for account/session MVP
"""

from fastapi import APIRouter
from app.api.endpoints import auth, chat, documents, graph, search

router = APIRouter()

router.include_router(auth.router, prefix="/auth", tags=["auth"])
router.include_router(documents.router, prefix="/documents", tags=["documents"])
router.include_router(graph.router, prefix="/graph", tags=["graph"])
router.include_router(search.router, prefix="/search", tags=["search"])
router.include_router(chat.router, prefix="/chat", tags=["chat"])
