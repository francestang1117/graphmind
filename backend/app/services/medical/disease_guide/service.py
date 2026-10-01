"""Application service for public disease guide reads."""

from .models import DiseaseGuide, DiseaseGuideSearchItem
from .repository import disease_guide_repository


class DiseaseGuideService:
    def search(self, query: str, limit: int = 20) -> list[DiseaseGuideSearchItem]:
        return disease_guide_repository.search(query, limit)

    def get(self, concept_id: str, language: str, region: str) -> DiseaseGuide | None:
        guide = disease_guide_repository.get(concept_id, language)
        if guide is None:
            return None
        if region.strip().upper() != guide.region.upper():
            return None
        return guide

    def concept_exists(self, concept_id: str) -> bool:
        return disease_guide_repository.concept_exists(concept_id)


disease_guide_service = DiseaseGuideService()
