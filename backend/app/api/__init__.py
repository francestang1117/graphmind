"""API router composition."""

from fastapi import APIRouter
from app.api.endpoints import auth, chat, documents, graph, scraper, search

router = APIRouter()

router.include_router(auth.router, prefix="/auth", tags=["auth"])
router.include_router(documents.router, prefix="/documents", tags=["documents"])
router.include_router(graph.router, prefix="/graph", tags=["graph"])
router.include_router(search.router, prefix="/search", tags=["search"])
router.include_router(chat.router, prefix="/chat", tags=["chat"])
router.include_router(scraper.router, prefix="/scraper", tags=["scraper"])
