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
        requested_region = region.strip().upper()
        if not requested_region or requested_region == guide.region.upper():
            return guide

        return guide.model_copy(
            update={
                "region": requested_region,
                "region_status": "not_verified",
                "region_note": (
                    f"治疗和监管信息目前只按 {guide.region.upper()} 资料核对；"
                    f"{requested_region} 的批准状态未知，请核对当地监管机构。"
                ),
            }
        )

    def concept_exists(self, concept_id: str) -> bool:
        return disease_guide_repository.concept_exists(concept_id)


disease_guide_service = DiseaseGuideService()
