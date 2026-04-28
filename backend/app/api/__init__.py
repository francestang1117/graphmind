"""API router composition."""

from fastapi import APIRouter
from app.api.endpoints import documents

router = APIRouter()

router.include_router(documents.router, prefix="/documents", tags=["documents"])
