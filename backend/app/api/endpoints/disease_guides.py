"""Public read-only endpoints for disease exploration guides."""

from fastapi import APIRouter, Query

from app.core.errors import AppError
from app.services.medical.disease_guide.models import (
    DiseaseGuide,
    DiseaseGuideSearchView,
)
from app.services.medical.disease_guide.service import disease_guide_service


router = APIRouter()


@router.get("/disease-guides/concepts/search", response_model=DiseaseGuideSearchView)
async def search_disease_guide_concepts(
    q: str = Query(min_length=1, max_length=120),
    limit: int = Query(default=20, ge=1, le=50),
) -> DiseaseGuideSearchView:
    return DiseaseGuideSearchView(items=disease_guide_service.search(q, limit))


@router.get("/disease-guides/{concept_id}", response_model=DiseaseGuide)
async def get_disease_guide(
    concept_id: str,
    language: str = Query(default="zh-CN", max_length=20),
    region: str = Query(default="JP", min_length=2, max_length=20),
) -> DiseaseGuide:
    guide = disease_guide_service.get(concept_id, language, region)
    if guide is not None:
        return guide

    if disease_guide_service.concept_exists(concept_id):
        raise AppError(
            code="disease_guide_not_ready",
            message="This disease is recognized, but its public guide is still being prepared.",
            status_code=404,
            details={"concept_id": concept_id},
        )
    raise AppError(
        code="disease_concept_not_found",
        message="The requested disease concept was not found.",
        status_code=404,
        details={"concept_id": concept_id},
    )
