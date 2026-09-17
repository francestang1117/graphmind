"""Coordinate local concept validation, scoped reads, and deterministic aggregation."""

from __future__ import annotations

from typing import Any, Callable

from app.services.medical.disease_profile.aggregator import (
    PROFILE_SECTIONS,
    DiseaseProfileAggregator,
)
from app.services.medical.disease_profile.exceptions import DiseaseProfileError
from app.services.medical.disease_profile.repository import (
    DiseaseProfileRepository,
    disease_profile_repository,
)
from app.services.medical.terminology import DiseaseOntologyError, get_default_ontology
from app.services.medical.terminology.normalizer import normalize_terminology_text


class DiseaseProfileService:
    """Application-facing facade for the disease profile read model."""

    def __init__(
        self,
        repository: DiseaseProfileRepository = disease_profile_repository,
        ontology_factory: Callable[[], Any] = get_default_ontology,
        aggregator: DiseaseProfileAggregator | None = None,
    ) -> None:
        self.repository = repository
        self.ontology_factory = ontology_factory
        self.aggregator = aggregator or DiseaseProfileAggregator()

    def create_link(
        self,
        *,
        user_id: str,
        workspace_id: str,
        document_id: str,
        concept_id: str,
        matched_alias: str = "",
        source_search_run_id: str | None = None,
    ) -> tuple[dict[str, Any], bool]:
        concept = self._concept(concept_id)
        alias = str(matched_alias or "").strip()
        if not alias:
            alias = concept.preferred_name_zh or concept.preferred_name_en
        allowed_aliases = {
            normalize_terminology_text(concept.preferred_name_en),
            normalize_terminology_text(concept.preferred_name_zh),
            *(normalize_terminology_text(item.text) for item in concept.aliases),
        }
        if normalize_terminology_text(alias) not in allowed_aliases:
            raise DiseaseProfileError(
                "The selected alias is not part of the local disease concept.",
                code="disease_link_invalid_source",
                status_code=422,
            )
        return self.repository.create_link(
            user_id=user_id,
            workspace_id=workspace_id,
            document_id=document_id,
            concept_id=concept.concept_id,
            preferred_name_en=concept.preferred_name_en,
            preferred_name_zh=concept.preferred_name_zh,
            matched_alias=alias,
            ontology_version=self._ontology_version(),
            source_search_run_id=source_search_run_id,
        )

    def delete_link(
        self,
        *,
        user_id: str,
        workspace_id: str,
        document_id: str,
        concept_id: str,
    ) -> bool:
        return self.repository.delete_link(
            user_id=user_id,
            workspace_id=workspace_id,
            document_id=document_id,
            concept_id=concept_id,
        )

    def search_concepts(self, query: str, *, limit: int = 20) -> list[dict[str, Any]]:
        """Search only the local ontology; this method has no network path."""
        normalized_query = normalize_terminology_text(query)
        if not normalized_query:
            return []
        ontology = self._ontology()
        ranked: list[tuple[int, str, Any, str]] = []
        for concept in ontology.concepts:
            candidates = [concept.preferred_name_en, concept.preferred_name_zh]
            candidates.extend(alias.text for alias in concept.aliases)
            best: tuple[int, str] | None = None
            for candidate in candidates:
                normalized = normalize_terminology_text(candidate)
                if not normalized:
                    continue
                if normalized == normalized_query:
                    score = 0
                elif normalized.startswith(normalized_query):
                    score = 1
                elif normalized_query in normalized:
                    score = 2
                else:
                    continue
                if best is None or score < best[0]:
                    best = (score, candidate)
            if best is not None:
                ranked.append((best[0], concept.concept_id, concept, best[1]))
        ranked.sort(key=lambda item: (item[0], item[1]))
        return [
            {
                "concept_id": concept.concept_id,
                "preferred_name_en": concept.preferred_name_en,
                "preferred_name_zh": concept.preferred_name_zh,
                "ontology_version": ontology.version,
                "matched_alias": matched_alias,
            }
            for _score, _concept_id, concept, matched_alias in ranked[: max(1, min(limit, 50))]
        ]

    def list_profiles(
        self,
        *,
        user_id: str,
        workspace_id: str,
        limit: int = 50,
        cursor_concept_id: str | None = None,
    ) -> dict[str, Any]:
        grouped = self.repository.load_profile_inputs(
            user_id=user_id,
            workspace_id=workspace_id,
        )
        concept_ids = sorted(grouped)
        if cursor_concept_id:
            concept_ids = [item for item in concept_ids if item > cursor_concept_id]
        selected = concept_ids[: max(1, min(int(limit), 50))]
        summaries = []
        for concept_id in selected:
            payload = self._aggregate(concept_id, grouped[concept_id], preview_limit=0)
            summaries.append(self._summary(payload))
        next_cursor = selected[-1] if len(concept_ids) > len(selected) and selected else None
        return {"items": summaries, "next_cursor": next_cursor}

    def get_profile(
        self,
        *,
        user_id: str,
        workspace_id: str,
        concept_id: str,
    ) -> dict[str, Any] | None:
        grouped = self.repository.load_profile_inputs(
            user_id=user_id,
            workspace_id=workspace_id,
            concept_id=concept_id,
        )
        records = grouped.get(concept_id)
        if not records:
            return None
        payload = self._aggregate(concept_id, records, preview_limit=5)
        preview_sections = payload.get("sections") or {}
        section_counts = payload.get("section_counts") or {}
        payload.pop("_all_sections", None)
        payload["sections"] = [
            {
                "section": section,
                "count": int(section_counts.get(section, 0)),
                "items": preview_sections.get(section, []),
            }
            for section in PROFILE_SECTIONS
        ]
        return payload

    def get_items(
        self,
        *,
        user_id: str,
        workspace_id: str,
        concept_id: str,
        section: str,
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, Any] | None:
        if section not in PROFILE_SECTIONS:
            raise DiseaseProfileError(
                "The requested disease profile section is invalid.",
                code="disease_profile_invalid_section",
                status_code=422,
            )
        grouped = self.repository.load_profile_inputs(
            user_id=user_id,
            workspace_id=workspace_id,
            concept_id=concept_id,
        )
        records = grouped.get(concept_id)
        if not records:
            return None
        payload = self._aggregate(concept_id, records, preview_limit=0)
        all_sections = payload.get("_all_sections") or {}
        items = list(all_sections.get(section) or [])
        page_limit = max(1, min(int(limit), 50))
        start = max(0, int(offset))
        return {
            "section": section,
            "items": items[start : start + page_limit],
            "total": len(items),
        }

    def list_unassigned_documents(
        self,
        *,
        user_id: str,
        workspace_id: str,
    ) -> list[dict[str, Any]]:
        return self.repository.list_unassigned_documents(
            user_id=user_id,
            workspace_id=workspace_id,
        )

    def _aggregate(
        self,
        concept_id: str,
        records: list[dict[str, Any]],
        *,
        preview_limit: int,
    ) -> dict[str, Any]:
        payload = self.aggregator.aggregate(
            concept_id=concept_id,
            inputs=records,
            preview_limit=preview_limit,
        )
        return payload

    def _concept(self, concept_id: str):
        concept = self._ontology().get(concept_id)
        if concept is None:
            raise DiseaseProfileError(
                "The disease concept was not found in the local ontology.",
                code="disease_concept_not_found",
                status_code=404,
            )
        return concept

    def _ontology(self):
        try:
            return self.ontology_factory()
        except DiseaseOntologyError as exc:
            raise DiseaseProfileError(
                "The local disease ontology is temporarily unavailable.",
                code="disease_profile_storage_unavailable",
                status_code=503,
            ) from exc

    def _ontology_version(self) -> str:
        return self._ontology().version

    @staticmethod
    def _summary(payload: dict[str, Any]) -> dict[str, Any]:
        return {
            key: payload.get(key)
            for key in (
                "concept_id",
                "preferred_name_en",
                "preferred_name_zh",
                "ontology_version",
                "document_count",
                "analysis_count",
                "external_article_count",
                "saved_question_count",
                "last_updated_at",
                "section_counts",
                "warnings",
            )
        }


disease_profile_service = DiseaseProfileService()
