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
    ProfileInputOptions,
    disease_profile_repository,
)
from app.services.medical.terminology import DiseaseOntologyError, get_default_ontology
from app.services.medical.terminology.normalizer import normalize_terminology_text


_ALL_PROFILE_INPUTS = ProfileInputOptions()
_MAX_PROFILE_ITEMS_OFFSET = 10_000
_SECTION_INPUT_OPTIONS = {
    "key_findings": ProfileInputOptions(
        analyses=True, evidence=True, literature_matches=False, clinician_questions=False
    ),
    "study_methods": ProfileInputOptions(
        analyses=True, evidence=True, literature_matches=False, clinician_questions=False
    ),
    "limitations": ProfileInputOptions(
        analyses=True, evidence=True, literature_matches=False, clinician_questions=False
    ),
    "what_it_means": ProfileInputOptions(
        analyses=True, evidence=True, literature_matches=False, clinician_questions=False
    ),
    "what_it_does_not_mean": ProfileInputOptions(
        analyses=True, evidence=True, literature_matches=False, clinician_questions=False
    ),
    "applicability": ProfileInputOptions(
        analyses=True, evidence=True, literature_matches=False, clinician_questions=False
    ),
    "future_research": ProfileInputOptions(
        analyses=True, evidence=True, literature_matches=False, clinician_questions=False
    ),
    "medical_terms": ProfileInputOptions(
        analyses=True, evidence=True, literature_matches=False, clinician_questions=False
    ),
    "clinician_questions": ProfileInputOptions(
        analyses=True, evidence=True, literature_matches=False, clinician_questions=True
    ),
    "external_studies": ProfileInputOptions(
        analyses=True, evidence=False, literature_matches=True, clinician_questions=False
    ),
}


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
        concept_page = self.repository.list_profile_concept_page(
            user_id=user_id,
            workspace_id=workspace_id,
            limit=limit,
            after_concept_id=cursor_concept_id,
        )
        concept_rows = concept_page.get("items") or []
        concept_ids = [str(row.get("concept_id")) for row in concept_rows]
        grouped = self.repository.load_profile_inputs(
            user_id=user_id,
            workspace_id=workspace_id,
            concept_ids=concept_ids,
            include=_ALL_PROFILE_INPUTS,
        )
        summaries = []
        for concept_id in concept_ids:
            records = grouped.get(concept_id)
            if records:
                payload = self.aggregator.aggregate_summary(
                    concept_id=concept_id,
                    inputs=records,
                )
                summaries.append(self._summary(payload))
        return {"items": summaries, "next_cursor": concept_page.get("next_cursor")}

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
            concept_ids=[concept_id],
            include=_ALL_PROFILE_INPUTS,
        )
        records = grouped.get(concept_id)
        if not records:
            return None
        payload = self.aggregator.aggregate_detail(
            concept_id=concept_id,
            inputs=records,
            preview_limit=5,
        )
        document_page = self.repository.list_profile_documents(
            user_id=user_id,
            workspace_id=workspace_id,
            concept_id=concept_id,
            limit=20,
        )
        payload["documents"] = (document_page or {}).get("items", [])
        payload["documents_next_cursor"] = (document_page or {}).get("next_cursor")
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
        if int(offset) < 0 or int(offset) > _MAX_PROFILE_ITEMS_OFFSET:
            raise DiseaseProfileError(
                "The requested disease profile item offset is invalid.",
                code="disease_profile_invalid_cursor",
                status_code=422,
            )
        grouped = self.repository.load_profile_inputs(
            user_id=user_id,
            workspace_id=workspace_id,
            concept_ids=[concept_id],
            include=_SECTION_INPUT_OPTIONS[section],
        )
        records = grouped.get(concept_id)
        if not records:
            return None
        payload = self.aggregator.aggregate_section(
            concept_id=concept_id,
            inputs=records,
            section=section,
        )
        all_sections = payload.get("_all_sections") or {}
        items = list(all_sections.get(section) or [])
        page_limit = max(1, min(int(limit), 50))
        start = max(0, int(offset))
        page_items = items[start : start + page_limit]
        next_offset = start + len(page_items)
        return {
            "section": section,
            "items": page_items,
            "total": int((payload.get("section_counts") or {}).get(section, len(items))),
            "truncated": bool(next_offset > _MAX_PROFILE_ITEMS_OFFSET and next_offset < len(items)),
        }

    def list_unassigned_documents(
        self,
        *,
        user_id: str,
        workspace_id: str,
        limit: int = 20,
        cursor_document_id: str | None = None,
    ) -> dict[str, Any]:
        return self.repository.list_unassigned_documents(
            user_id=user_id,
            workspace_id=workspace_id,
            limit=limit,
            after_document_id=cursor_document_id,
        )

    def list_profile_documents(
        self,
        *,
        user_id: str,
        workspace_id: str,
        concept_id: str,
        limit: int = 20,
        cursor_document_id: str | None = None,
    ) -> dict[str, Any] | None:
        return self.repository.list_profile_documents(
            user_id=user_id,
            workspace_id=workspace_id,
            concept_id=concept_id,
            limit=limit,
            after_document_id=cursor_document_id,
        )

    def list_external_source_documents(
        self,
        *,
        user_id: str,
        workspace_id: str,
        concept_id: str,
        source: str,
        external_id: str,
        limit: int = 20,
        cursor_document_id: str | None = None,
    ) -> dict[str, Any] | None:
        return self.repository.list_external_source_documents(
            user_id=user_id,
            workspace_id=workspace_id,
            concept_id=concept_id,
            source=source,
            external_id=external_id,
            limit=limit,
            after_document_id=cursor_document_id,
        )

    def _aggregate(
        self,
        concept_id: str,
        records: list[dict[str, Any]],
        *,
        preview_limit: int,
        enabled_sections: set[str] | None = None,
    ) -> dict[str, Any]:
        payload = self.aggregator.aggregate(
            concept_id=concept_id,
            inputs=records,
            preview_limit=preview_limit,
            enabled_sections=enabled_sections,
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
