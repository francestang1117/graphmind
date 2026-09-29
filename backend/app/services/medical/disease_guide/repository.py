"""Versioned file-backed storage for public disease guides."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from app.services.medical.disease_profile.service import disease_profile_service

from .models import DiseaseGuide, DiseaseGuideSearchItem


GUIDE_DATA_DIR = Path(__file__).with_name("data")


def normalize_language(language: str) -> str:
    normalized = language.strip().replace("_", "-").lower()
    if normalized in {"zh", "zh-cn", "zh-hans"}:
        return "zh-CN"
    if normalized.startswith("en"):
        return "en"
    return language.strip()


@lru_cache(maxsize=1)
def load_guides() -> dict[tuple[str, str], DiseaseGuide]:
    guides: dict[tuple[str, str], DiseaseGuide] = {}
    for path in sorted(GUIDE_DATA_DIR.glob("*.json")):
        guide = DiseaseGuide.model_validate_json(path.read_text(encoding="utf-8"))
        key = (guide.concept_id, guide.language)
        if key in guides:
            raise RuntimeError(f"duplicate disease guide: {key}")
        guides[key] = guide
    return guides


class DiseaseGuideRepository:
    def get(self, concept_id: str, language: str) -> DiseaseGuide | None:
        return load_guides().get((concept_id, normalize_language(language)))

    def search(self, query: str, limit: int) -> list[DiseaseGuideSearchItem]:
        concepts = disease_profile_service.search_concepts(query, limit=limit)
        available = load_guides()
        results: list[DiseaseGuideSearchItem] = []
        for concept in concepts:
            languages = sorted(
                language
                for concept_id, language in available
                if concept_id == concept["concept_id"]
            )
            results.append(
                DiseaseGuideSearchItem(
                    concept_id=concept["concept_id"],
                    preferred_name_en=concept["preferred_name_en"],
                    preferred_name_zh=concept["preferred_name_zh"],
                    matched_alias=concept.get("matched_alias"),
                    guide_status="available" if languages else "preparing",
                    guide_languages=languages,
                )
            )
        return results

    def concept_exists(self, concept_id: str) -> bool:
        return disease_profile_service._ontology().get(concept_id) is not None


disease_guide_repository = DiseaseGuideRepository()
