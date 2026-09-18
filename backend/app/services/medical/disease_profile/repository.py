"""Scoped database reads and writes for document disease associations."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from dataclasses import dataclass
import json
import logging
from typing import Any, Callable, Iterable, Sequence
import uuid

from app.core.database import SessionLocal, db_enabled
from app.models.persistence import (
    ClinicianQuestionRecord,
    DocumentDiseaseLinkRecord,
    DocumentRecord,
    LiteratureArticleRecord,
    LiteratureEvidenceMatchRecord,
    LiteratureMatchRunRecord,
    LiteratureSearchRunRecord,
    MedicalAnalysisEvidenceRecord,
    MedicalAnalysisResultRecord,
    MedicalAnalysisRunRecord,
    MedicalDocumentProfileRecord,
)
from app.services.medical.disease_profile.exceptions import DiseaseProfileError

try:
    from sqlalchemy import delete, func, select
    from sqlalchemy.exc import IntegrityError, SQLAlchemyError
except ImportError:  # pragma: no cover - dependencies are installed in app/test runs
    delete = None
    func = None
    select = None
    IntegrityError = Exception
    SQLAlchemyError = Exception


log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProfileInputOptions:
    """Select the derived tables needed by one profile read.

    The options are deliberately server-owned.  Callers choose a known
    section mapping instead of turning request input into table selection.
    """

    analyses: bool = True
    evidence: bool = True
    literature_matches: bool = True
    clinician_questions: bool = True


def is_current_valid_analysis(run: Any, result: Any, document: Any) -> bool:
    """Return whether an analysis still describes the current document parse."""
    if not run or not result or not document:
        return False

    def value(item: Any, name: str, default: Any = None) -> Any:
        if isinstance(item, dict):
            return item.get(name, default)
        return getattr(item, name, default)

    return bool(
        value(run, "status") == "succeeded"
        and value(result, "validation_status") == "validated"
        and value(run, "is_current")
        and value(run, "source_hash") == value(document, "file_hash", "")
        and value(document, "parsed_source_hash", "")
        and value(run, "parsed_source_hash") == value(document, "parsed_source_hash", "")
    )


class DiseaseProfileRepository:
    """Keep profiles scoped and assign each document one primary disease."""

    def __init__(
        self,
        session_factory=SessionLocal,
        enabled: Callable[[], bool] = db_enabled,
    ) -> None:
        self.session_factory = session_factory
        self.enabled = enabled

    def available(self) -> bool:
        return bool(
            self.enabled()
            and self.session_factory
            and select
            and delete
            and DocumentDiseaseLinkRecord
            and DocumentRecord
            and MedicalAnalysisRunRecord
            and LiteratureMatchRunRecord
            and ClinicianQuestionRecord
        )

    def create_link(
        self,
        *,
        user_id: str,
        workspace_id: str,
        document_id: str,
        concept_id: str,
        preferred_name_en: str,
        preferred_name_zh: str,
        matched_alias: str,
        ontology_version: str,
        source_search_run_id: str | None = None,
    ) -> tuple[dict[str, Any], bool]:
        """Create an idempotent, scope-checked association."""
        self._require_available()
        try:
            with self.session_factory() as db:
                document = db.scalars(
                    select(DocumentRecord).where(
                        DocumentRecord.id == document_id,
                        DocumentRecord.user_id == user_id,
                        DocumentRecord.workspace_id == workspace_id,
                        DocumentRecord.deleted_at.is_(None),
                    )
                ).first()
                if not document:
                    raise DiseaseProfileError(
                        "The document was not found in this research project.",
                        code="disease_link_document_not_found",
                        status_code=404,
                    )

                existing = self._find_link(
                    db,
                    user_id=user_id,
                    workspace_id=workspace_id,
                    document_id=document.id,
                    concept_id=concept_id,
                )
                if existing:
                    db.commit()
                    return _link_dict(existing), False

                # Derived analysis belongs to the document, not to an
                # individual link. Rejecting a second primary concept keeps
                # the profile read model from copying evidence across diseases.
                primary = self._find_document_link(
                    db,
                    user_id=user_id,
                    workspace_id=workspace_id,
                    document_id=document.id,
                )
                if primary:
                    raise DiseaseProfileError(
                        "This document already has a primary disease. Remove the existing link before choosing another.",
                        code="disease_link_primary_exists",
                        status_code=409,
                    )

                if source_search_run_id:
                    search = db.scalars(
                        select(LiteratureSearchRunRecord).where(
                            LiteratureSearchRunRecord.id == source_search_run_id,
                            LiteratureSearchRunRecord.user_id == user_id,
                            LiteratureSearchRunRecord.workspace_id == workspace_id,
                            LiteratureSearchRunRecord.document_id == document.id,
                            LiteratureSearchRunRecord.status == "succeeded",
                            LiteratureSearchRunRecord.external_search_confirmed_at.is_not(None),
                        )
                    ).first()
                    if not search or not _search_contains_concept(search, concept_id):
                        raise DiseaseProfileError(
                            "The search run cannot be used as this disease link source.",
                            code="disease_link_invalid_source",
                            status_code=422,
                        )

                row = DocumentDiseaseLinkRecord(
                    id=uuid.uuid4().hex,
                    user_id=user_id,
                    workspace_id=workspace_id,
                    document_id=document.id,
                    concept_id=concept_id,
                    preferred_name_en=preferred_name_en,
                    preferred_name_zh=preferred_name_zh,
                    matched_alias=matched_alias,
                    ontology_version=ontology_version,
                    link_source=("confirmed_search" if source_search_run_id else "manual_selection"),
                    source_search_run_id=source_search_run_id,
                    created_at=_utc_now(),
                    updated_at=_utc_now(),
                )
                db.add(row)
                try:
                    db.flush()
                except IntegrityError:
                    # A concurrent identical request can win the unique key;
                    # read the scoped winner and preserve idempotent semantics.
                    db.rollback()
                    existing = self._find_link(
                        db,
                        user_id=user_id,
                        workspace_id=workspace_id,
                        document_id=document.id,
                        concept_id=concept_id,
                    )
                    if existing:
                        db.commit()
                        return _link_dict(existing), False
                    primary = self._find_document_link(
                        db,
                        user_id=user_id,
                        workspace_id=workspace_id,
                        document_id=document.id,
                    )
                    if primary:
                        raise DiseaseProfileError(
                            "This document already has a primary disease. Remove the existing link before choosing another.",
                            code="disease_link_primary_exists",
                            status_code=409,
                        )
                    raise
                db.commit()
                return _link_dict(row), True
        except DiseaseProfileError:
            raise
        except SQLAlchemyError as exc:
            log.warning("Could not create disease link for %s", document_id)
            raise DiseaseProfileError(
                "Could not save the disease document link.",
                code="disease_profile_storage_unavailable",
                status_code=503,
            ) from exc

    def delete_link(
        self,
        *,
        user_id: str,
        workspace_id: str,
        document_id: str,
        concept_id: str,
    ) -> bool:
        self._require_available()
        try:
            with self.session_factory() as db:
                document_exists = db.scalar(
                    select(DocumentRecord.id).where(
                        DocumentRecord.id == document_id,
                        DocumentRecord.user_id == user_id,
                        DocumentRecord.workspace_id == workspace_id,
                        DocumentRecord.deleted_at.is_(None),
                    )
                )
                if not document_exists:
                    raise DiseaseProfileError(
                        "The document was not found in this research project.",
                        code="disease_link_document_not_found",
                        status_code=404,
                    )
                result = db.execute(
                    delete(DocumentDiseaseLinkRecord).where(
                        DocumentDiseaseLinkRecord.user_id == user_id,
                        DocumentDiseaseLinkRecord.workspace_id == workspace_id,
                        DocumentDiseaseLinkRecord.document_id == document_id,
                        DocumentDiseaseLinkRecord.concept_id == concept_id,
                    )
                )
                db.commit()
                return bool(result.rowcount)
        except DiseaseProfileError:
            raise
        except SQLAlchemyError as exc:
            log.warning("Could not delete disease link for %s", document_id)
            raise DiseaseProfileError(
                "Could not remove the disease document link.",
                code="disease_profile_storage_unavailable",
                status_code=503,
            ) from exc

    def delete_for_document(
        self,
        document_id: str,
        *,
        user_id: str,
        workspace_id: str | None = None,
    ) -> None:
        """Remove associations after a soft-deleted document is cleaned."""
        if not self.available() or not document_id:
            return
        try:
            with self.session_factory() as db:
                conditions = [
                    DocumentDiseaseLinkRecord.document_id == document_id,
                    DocumentDiseaseLinkRecord.user_id == user_id,
                ]
                if workspace_id is not None:
                    conditions.append(DocumentDiseaseLinkRecord.workspace_id == workspace_id)
                db.execute(delete(DocumentDiseaseLinkRecord).where(*conditions))
                db.commit()
        except SQLAlchemyError as exc:
            log.warning("Could not delete disease links for %s", document_id)
            raise DiseaseProfileError(
                "Could not clean up disease document links.",
                code="disease_profile_storage_unavailable",
                status_code=503,
            ) from exc

    def list_profile_concept_page(
        self,
        *,
        user_id: str,
        workspace_id: str,
        limit: int,
        after_concept_id: str | None = None,
    ) -> dict[str, Any]:
        """Return one bounded, scope-checked page of live profile concepts."""
        self._require_available()
        page_size = max(1, min(int(limit), 50))
        try:
            with self.session_factory() as db:
                statement = (
                    select(
                        DocumentDiseaseLinkRecord.concept_id.label("concept_id"),
                        DocumentDiseaseLinkRecord.preferred_name_en.label("preferred_name_en"),
                        DocumentDiseaseLinkRecord.preferred_name_zh.label("preferred_name_zh"),
                        DocumentDiseaseLinkRecord.ontology_version.label("ontology_version"),
                        func.count(DocumentDiseaseLinkRecord.document_id).label("document_count"),
                        func.max(DocumentDiseaseLinkRecord.updated_at).label("last_updated_at"),
                    )
                    .join(
                        DocumentRecord,
                        DocumentRecord.id == DocumentDiseaseLinkRecord.document_id,
                    )
                    .where(
                        DocumentDiseaseLinkRecord.user_id == user_id,
                        DocumentDiseaseLinkRecord.workspace_id == workspace_id,
                        DocumentRecord.user_id == user_id,
                        DocumentRecord.workspace_id == workspace_id,
                        DocumentRecord.deleted_at.is_(None),
                    )
                    .group_by(
                        DocumentDiseaseLinkRecord.concept_id,
                        DocumentDiseaseLinkRecord.preferred_name_en,
                        DocumentDiseaseLinkRecord.preferred_name_zh,
                        DocumentDiseaseLinkRecord.ontology_version,
                    )
                    .order_by(DocumentDiseaseLinkRecord.concept_id)
                    .limit(page_size + 1)
                )
                if after_concept_id:
                    statement = statement.where(
                        DocumentDiseaseLinkRecord.concept_id > after_concept_id
                    )
                rows = db.execute(statement).mappings().all()
                page = rows[:page_size]
                return {
                    "items": [
                        {
                            "concept_id": str(row["concept_id"]),
                            "preferred_name_en": str(row["preferred_name_en"] or ""),
                            "preferred_name_zh": str(row["preferred_name_zh"] or ""),
                            "ontology_version": str(row["ontology_version"] or ""),
                            "document_count": int(row["document_count"] or 0),
                            "last_updated_at": _iso(row["last_updated_at"]),
                        }
                        for row in page
                    ],
                    "next_cursor": (
                        str(page[-1]["concept_id"])
                        if len(rows) > page_size and page
                        else None
                    ),
                }
        except SQLAlchemyError as exc:
            log.warning("Could not list disease profile concepts")
            raise DiseaseProfileError(
                "Disease profile data is temporarily unavailable.",
                code="disease_profile_storage_unavailable",
                status_code=503,
            ) from exc

    def load_profile_inputs(
        self,
        *,
        user_id: str,
        workspace_id: str,
        concept_ids: Sequence[str] | None = None,
        include: ProfileInputOptions | None = None,
        concept_id: str | None = None,
    ) -> dict[str, list[dict[str, Any]]]:
        """Batch-load selected profile inputs without an N+1 query path.

        ``concept_id`` remains as a compatibility alias for older internal
        callers.  New reads must pass ``concept_ids`` explicitly; omitting
        both returns an empty result instead of scanning a whole workspace.
        """
        self._require_available()
        if concept_ids is None:
            concept_ids = [concept_id] if concept_id else []
        selected_concepts = list(dict.fromkeys(str(value) for value in concept_ids if value))
        if not selected_concepts:
            return {}
        options = include or ProfileInputOptions()
        try:
            with self.session_factory() as db:
                link_query = (
                    select(DocumentDiseaseLinkRecord, DocumentRecord)
                    .join(
                        DocumentRecord,
                        DocumentRecord.id == DocumentDiseaseLinkRecord.document_id,
                    )
                    .where(
                        DocumentDiseaseLinkRecord.user_id == user_id,
                        DocumentDiseaseLinkRecord.workspace_id == workspace_id,
                        DocumentRecord.user_id == user_id,
                        DocumentRecord.workspace_id == workspace_id,
                        DocumentRecord.deleted_at.is_(None),
                        DocumentDiseaseLinkRecord.concept_id.in_(selected_concepts),
                    )
                    .order_by(
                        DocumentDiseaseLinkRecord.document_id,
                        DocumentDiseaseLinkRecord.created_at,
                        DocumentDiseaseLinkRecord.id,
                    )
                )
                link_rows = db.execute(link_query).all()
                if not link_rows:
                    return {}

                documents = {
                    document.id: _document_dict(document)
                    for _link, document in link_rows
                }
                document_ids = list(documents)
                # Keep a defensive first-link fallback for databases upgraded
                # from the old multi-disease schema. The migration collapses
                # duplicates, but reads must not fan out evidence if a legacy
                # package is briefly mounted before startup migration runs.
                links_by_document: dict[str, dict[str, Any]] = {}
                for link, _document in link_rows:
                    links_by_document.setdefault(link.document_id, _link_dict(link))

                needs_analyses = bool(
                    options.analyses
                    or options.evidence
                    or options.literature_matches
                    or options.clinician_questions
                )
                analysis_rows = []
                if needs_analyses:
                    analysis_rows = db.execute(
                        select(MedicalAnalysisRunRecord, MedicalAnalysisResultRecord)
                        .outerjoin(
                            MedicalAnalysisResultRecord,
                            MedicalAnalysisResultRecord.run_id == MedicalAnalysisRunRecord.id,
                        )
                        .where(
                            MedicalAnalysisRunRecord.user_id == user_id,
                            MedicalAnalysisRunRecord.workspace_id == workspace_id,
                            MedicalAnalysisRunRecord.document_id.in_(document_ids),
                        )
                        .order_by(
                            MedicalAnalysisRunRecord.document_id,
                            MedicalAnalysisRunRecord.created_at.desc(),
                        )
                    ).all()
                evidence_by_run = self._load_evidence(
                    db,
                    [row[0].id for row in analysis_rows],
                ) if options.evidence else {}
                analyses_by_document: dict[str, list[dict[str, Any]]] = defaultdict(list)
                for run, result in analysis_rows:
                    document = documents.get(run.document_id)
                    if not document:
                        continue
                    report = _loads_json(result.report_json, None) if result else None
                    source_current = is_current_valid_analysis(run, result, document)
                    report_valid = isinstance(report, dict)
                    warnings: list[str] = []
                    if source_current and not report_valid:
                        warnings.append("analysis_report_unavailable")
                    analyses_by_document[run.document_id].append(
                        {
                            "run": _analysis_run_dict(run, result),
                            "report": report if source_current and report_valid else None,
                            "evidence": evidence_by_run.get(run.id, []) if source_current else [],
                            "valid": bool(source_current and report_valid),
                            "source_current": source_current,
                            "warnings": warnings,
                        }
                    )

                match_runs = []
                if options.literature_matches:
                    match_runs = db.scalars(
                        select(LiteratureMatchRunRecord)
                        .join(
                            LiteratureSearchRunRecord,
                            LiteratureSearchRunRecord.id == LiteratureMatchRunRecord.search_run_id,
                        )
                        .where(
                            LiteratureMatchRunRecord.user_id == user_id,
                            LiteratureMatchRunRecord.workspace_id == workspace_id,
                            LiteratureMatchRunRecord.document_id.in_(document_ids),
                            LiteratureMatchRunRecord.status == "completed",
                            LiteratureSearchRunRecord.status == "succeeded",
                        )
                        .order_by(
                            LiteratureMatchRunRecord.document_id,
                            LiteratureMatchRunRecord.updated_at.desc(),
                        )
                    ).all()
                match_run_ids = [row.id for row in match_runs]
                match_rows = []
                if options.literature_matches and match_run_ids:
                    match_rows = db.execute(
                        select(LiteratureEvidenceMatchRecord, LiteratureArticleRecord)
                        .join(
                            LiteratureArticleRecord,
                            LiteratureArticleRecord.id
                            == LiteratureEvidenceMatchRecord.article_id,
                        )
                        .where(
                            LiteratureEvidenceMatchRecord.match_run_id.in_(match_run_ids)
                        )
                        .order_by(
                            LiteratureEvidenceMatchRecord.match_run_id,
                            LiteratureEvidenceMatchRecord.candidate_rank,
                            LiteratureEvidenceMatchRecord.relevance_score.desc(),
                            LiteratureArticleRecord.source,
                            LiteratureArticleRecord.external_id,
                        )
                    ).all()
                match_runs_by_id = {row.id: row for row in match_runs}
                matches_by_document: dict[str, list[dict[str, Any]]] = defaultdict(list)
                for match, article in match_rows:
                    match_run = match_runs_by_id.get(match.match_run_id)
                    if not match_run:
                        continue
                    matches_by_document[match_run.document_id].append(
                        {
                            "match_run_id": match_run.id,
                            "analysis_run_id": match_run.analysis_run_id,
                            "finding_id": match.finding_id,
                            "relevance_score": match.relevance_score,
                            "match_specificity": match.match_specificity,
                            "candidate_rank": match.candidate_rank,
                            "article": _article_dict(article),
                        }
                    )

                question_rows = []
                if options.clinician_questions:
                    question_rows = db.scalars(
                        select(ClinicianQuestionRecord).where(
                            ClinicianQuestionRecord.user_id == user_id,
                            ClinicianQuestionRecord.workspace_id == workspace_id,
                            ClinicianQuestionRecord.document_id.in_(document_ids),
                            ClinicianQuestionRecord.status != "dismissed",
                        )
                        .order_by(
                            ClinicianQuestionRecord.document_id,
                            ClinicianQuestionRecord.position,
                            ClinicianQuestionRecord.created_at,
                            ClinicianQuestionRecord.id,
                        )
                    ).all()
                questions_by_document: dict[str, list[dict[str, Any]]] = defaultdict(list)
                for row in question_rows:
                    # Intentionally omit user_note: it is private to Visit Prep.
                    questions_by_document[row.document_id].append(_question_dict(row))

                grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
                for document_id, document in documents.items():
                    link = links_by_document.get(document_id)
                    if not link:
                        continue
                    grouped[link["concept_id"]].append(
                        {
                            "link": link,
                            "document": document,
                            "analyses": analyses_by_document.get(document_id, []),
                            "matches": matches_by_document.get(document_id, []),
                            "questions": questions_by_document.get(document_id, []),
                        }
                    )
                return dict(grouped)
        except DiseaseProfileError:
            raise
        except SQLAlchemyError as exc:
            log.warning("Could not load disease profile inputs")
            raise DiseaseProfileError(
                "Disease profile data is temporarily unavailable.",
                code="disease_profile_storage_unavailable",
                status_code=503,
            ) from exc

    def list_unassigned_documents(
        self,
        *,
        user_id: str,
        workspace_id: str,
    ) -> list[dict[str, Any]]:
        """Return classified live documents that have no disease link."""
        self._require_available()
        try:
            with self.session_factory() as db:
                linked = select(DocumentDiseaseLinkRecord.document_id).where(
                    DocumentDiseaseLinkRecord.user_id == user_id,
                    DocumentDiseaseLinkRecord.workspace_id == workspace_id,
                    DocumentDiseaseLinkRecord.document_id == DocumentRecord.id,
                )
                rows = db.execute(
                    select(DocumentRecord, MedicalDocumentProfileRecord)
                    .join(
                        MedicalDocumentProfileRecord,
                        MedicalDocumentProfileRecord.document_id == DocumentRecord.id,
                    )
                    .where(
                        DocumentRecord.user_id == user_id,
                        DocumentRecord.workspace_id == workspace_id,
                        DocumentRecord.deleted_at.is_(None),
                        MedicalDocumentProfileRecord.user_id == user_id,
                        MedicalDocumentProfileRecord.workspace_id == workspace_id,
                        MedicalDocumentProfileRecord.document_kind != "unknown",
                        ~linked.exists(),
                    )
                    .order_by(DocumentRecord.modified_at.desc(), DocumentRecord.id),
                ).all()
                return [
                    {
                        "document_id": document.id,
                        "title": (document.original_filename or document.filename or "Untitled document")[:255],
                        "document_kind": profile.document_kind,
                        "language": profile.language or document.language or "unknown",
                        "document_date": document.document_date or "",
                        "medical_confidence": max(0.0, min(1.0, float(profile.confidence or 0))),
                        "classifier_version": profile.classifier_version,
                        "warnings": _string_list(_loads_json(profile.warnings_json, []), 20),
                    }
                    for document, profile in rows
                ]
        except SQLAlchemyError as exc:
            log.warning("Could not list unassigned disease documents")
            raise DiseaseProfileError(
                "Disease profile data is temporarily unavailable.",
                code="disease_profile_storage_unavailable",
                status_code=503,
            ) from exc

    def _load_evidence(self, db, run_ids: Iterable[str]) -> dict[str, list[dict[str, Any]]]:
        ids = list(run_ids)
        if not ids:
            return {}
        rows = db.scalars(
            select(MedicalAnalysisEvidenceRecord)
            .where(MedicalAnalysisEvidenceRecord.run_id.in_(ids))
            .order_by(
                MedicalAnalysisEvidenceRecord.run_id,
                MedicalAnalysisEvidenceRecord.finding_id,
                MedicalAnalysisEvidenceRecord.id,
            )
        ).all()
        result: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            result[row.run_id].append(_evidence_dict(row))
        return dict(result)

    @staticmethod
    def _find_link(
        db,
        *,
        user_id: str,
        workspace_id: str,
        document_id: str,
        concept_id: str,
    ) -> DocumentDiseaseLinkRecord | None:
        return db.scalars(
            select(DocumentDiseaseLinkRecord).where(
                DocumentDiseaseLinkRecord.user_id == user_id,
                DocumentDiseaseLinkRecord.workspace_id == workspace_id,
                DocumentDiseaseLinkRecord.document_id == document_id,
                DocumentDiseaseLinkRecord.concept_id == concept_id,
            )
        ).first()

    @staticmethod
    def _find_document_link(
        db,
        *,
        user_id: str,
        workspace_id: str,
        document_id: str,
    ) -> DocumentDiseaseLinkRecord | None:
        return db.scalars(
            select(DocumentDiseaseLinkRecord)
            .where(
                DocumentDiseaseLinkRecord.user_id == user_id,
                DocumentDiseaseLinkRecord.workspace_id == workspace_id,
                DocumentDiseaseLinkRecord.document_id == document_id,
            )
            .order_by(
                DocumentDiseaseLinkRecord.created_at,
                DocumentDiseaseLinkRecord.id,
            )
        ).first()

    def _require_available(self) -> None:
        if not self.available():
            raise DiseaseProfileError(
                "Disease profile persistence is unavailable.",
                code="disease_profile_storage_unavailable",
                status_code=503,
            )


def _link_dict(row: DocumentDiseaseLinkRecord) -> dict[str, Any]:
    return {
        "id": row.id,
        "document_id": row.document_id,
        "concept_id": row.concept_id,
        "preferred_name_en": row.preferred_name_en,
        "preferred_name_zh": row.preferred_name_zh or "",
        "matched_alias": row.matched_alias or "",
        "ontology_version": row.ontology_version,
        "link_source": row.link_source,
        "source_search_run_id": row.source_search_run_id,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }


def _document_dict(row: DocumentRecord) -> dict[str, Any]:
    return {
        "document_id": row.id,
        "title": (row.original_filename or row.filename or "Untitled document")[:255],
        "document_kind": row.document_kind or "unknown",
        "language": row.language or "unknown",
        "document_date": row.document_date or "",
        "file_hash": row.file_hash or "",
        "parsed_source_hash": row.parsed_source_hash or "",
        "modified_at": _iso(row.modified_at),
    }


def _analysis_run_dict(
    row: MedicalAnalysisRunRecord,
    result: MedicalAnalysisResultRecord | None,
) -> dict[str, Any]:
    return {
        "run_id": row.id,
        "document_id": row.document_id,
        "status": row.status,
        "source_hash": row.source_hash,
        "parsed_source_hash": row.parsed_source_hash or "",
        "schema_version": row.schema_version,
        "is_current": bool(row.is_current),
        "validation_status": result.validation_status if result else "",
        "completed_at": _iso(row.completed_at),
        "updated_at": _iso(row.updated_at),
    }


def _evidence_dict(row: MedicalAnalysisEvidenceRecord) -> dict[str, Any]:
    return {
        "id": row.id,
        "evidence_id": row.evidence_id or row.id,
        "finding_id": row.finding_id,
        "chunk_id": row.chunk_id,
        "section_id": row.section_id,
        "section_type": row.section_type or "unknown",
        "section_title": row.section_title or "",
        "page_start": row.page_start,
        "page_end": row.page_end,
        "quote": row.quoted_text,
        "character_start": row.character_start,
        "character_end": row.character_end,
    }


def _article_dict(row: LiteratureArticleRecord) -> dict[str, Any]:
    return {
        "id": row.id,
        "source": row.source,
        "external_id": row.external_id,
        "doi": row.doi,
        "pmcid": row.pmcid,
        "title": row.title,
        "journal": row.journal,
        "publication_date": row.publication_date or None,
        "publication_year": row.publication_year,
        "publication_types": _loads_json(row.publication_types_json, []),
        "language": row.language,
        "source_url": row.source_url,
        "retraction_status": row.retraction_status or "unknown",
        "metadata_hash": row.metadata_hash,
    }


def _question_dict(row: ClinicianQuestionRecord) -> dict[str, Any]:
    return {
        "id": row.id,
        "document_id": row.document_id,
        "analysis_run_id": row.analysis_run_id,
        "suggestion_id": row.suggestion_id,
        "question": row.question,
        "rationale": row.rationale,
        "category": row.category,
        "topic": row.topic,
        "source_kind": row.source_kind,
        "source_id": row.source_id,
        "evidence_ids": _loads_json(row.evidence_ids_json, []),
        "language": row.language,
        "status": row.status,
        "position": row.position,
        "version": row.version,
    }


def _search_contains_concept(row: LiteratureSearchRunRecord, concept_id: str) -> bool:
    concepts = _loads_json(row.detected_concepts_json, [])
    if not isinstance(concepts, list):
        return False
    return any(
        isinstance(item, dict)
        and item.get("concept_id") == concept_id
        and item.get("source") == "local_ontology"
        for item in concepts
    )


def _loads_json(value: str | None, default: Any) -> Any:
    try:
        return json.loads(value or "")
    except (TypeError, json.JSONDecodeError):
        return default


def _string_list(value: Any, limit: int) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = str(item or "").strip()
        if text and text not in seen:
            result.append(text)
            seen.add(text)
            if len(result) >= limit:
                break
    return result


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str:
    return value.isoformat() if value else ""


disease_profile_repository = DiseaseProfileRepository()
