"""Scoped database reads and writes for document disease associations."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from dataclasses import dataclass
import json
import logging
from typing import Any, Callable, Iterable, Mapping, Sequence
import uuid

from pydantic import ValidationError

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
from app.services.medical.ai.models import MedicalInsightReport

try:
    from sqlalchemy import delete, func, select
    from sqlalchemy.orm import aliased
    from sqlalchemy.exc import IntegrityError, SQLAlchemyError
except ImportError:  # pragma: no cover - dependencies are installed in app/test runs
    delete = None
    func = None
    select = None
    IntegrityError = Exception
    SQLAlchemyError = Exception
    aliased = None


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
                    # A concept is the stable profile and cursor identity.
                    # Names and ontology versions may change between links,
                    # so they must not split one profile into multiple rows.
                    select(
                        DocumentDiseaseLinkRecord.concept_id.label("concept_id"),
                        func.count(
                            func.distinct(DocumentDiseaseLinkRecord.document_id)
                        ).label("document_count"),
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
        document_ids: Sequence[str] | None = None,
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
        selected_documents = list(
            dict.fromkeys(str(value) for value in (document_ids or []) if value)
        )
        options = include or ProfileInputOptions()
        try:
            with self.session_factory() as db:
                link_filters = [
                    DocumentDiseaseLinkRecord.user_id == user_id,
                    DocumentDiseaseLinkRecord.workspace_id == workspace_id,
                    DocumentRecord.user_id == user_id,
                    DocumentRecord.workspace_id == workspace_id,
                    DocumentRecord.deleted_at.is_(None),
                    DocumentDiseaseLinkRecord.concept_id.in_(selected_concepts),
                ]
                if selected_documents:
                    link_filters.append(
                        DocumentDiseaseLinkRecord.document_id.in_(selected_documents)
                    )
                link_query = (
                    select(DocumentDiseaseLinkRecord, DocumentRecord)
                    .join(
                        DocumentRecord,
                        DocumentRecord.id == DocumentDiseaseLinkRecord.document_id,
                    )
                    .where(*link_filters)
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

    def load_comparison_inputs(
        self,
        *,
        user_id: str,
        workspace_id: str,
        concept_id: str,
        document_ids: Sequence[str],
    ) -> list[dict[str, Any]]:
        """Load selected documents and exactly one current validated run each.

        Comparison reads use a dedicated query path instead of the general
        profile loader. The latter intentionally exposes history for profile
        status and expiry views; a comparison must never mix that history with
        the current report and its evidence.
        """
        selected_documents = list(dict.fromkeys(str(value) for value in document_ids if value))
        if not selected_documents:
            return []
        self._require_available()
        try:
            with self.session_factory() as db:
                link_rows = db.execute(
                    select(DocumentDiseaseLinkRecord, DocumentRecord)
                    .join(
                        DocumentRecord,
                        DocumentRecord.id == DocumentDiseaseLinkRecord.document_id,
                    )
                    .where(
                        DocumentDiseaseLinkRecord.user_id == user_id,
                        DocumentDiseaseLinkRecord.workspace_id == workspace_id,
                        DocumentDiseaseLinkRecord.concept_id == concept_id,
                        DocumentDiseaseLinkRecord.document_id.in_(selected_documents),
                        DocumentRecord.user_id == user_id,
                        DocumentRecord.workspace_id == workspace_id,
                        DocumentRecord.deleted_at.is_(None),
                    )
                    .order_by(
                        DocumentDiseaseLinkRecord.document_id,
                        DocumentDiseaseLinkRecord.created_at,
                        DocumentDiseaseLinkRecord.id,
                    )
                ).all()
                documents: dict[str, dict[str, Any]] = {}
                for _link, document in link_rows:
                    documents.setdefault(document.id, _document_dict(document))
                if not documents:
                    return []

                current_rows = db.execute(
                    select(MedicalAnalysisRunRecord, MedicalAnalysisResultRecord)
                    .join(
                        MedicalAnalysisResultRecord,
                        MedicalAnalysisResultRecord.run_id == MedicalAnalysisRunRecord.id,
                    )
                    .join(
                        DocumentRecord,
                        DocumentRecord.id == MedicalAnalysisRunRecord.document_id,
                    )
                    .where(
                        MedicalAnalysisRunRecord.user_id == user_id,
                        MedicalAnalysisRunRecord.workspace_id == workspace_id,
                        MedicalAnalysisRunRecord.document_id.in_(list(documents)),
                        MedicalAnalysisRunRecord.status == "succeeded",
                        MedicalAnalysisRunRecord.is_current.is_(True),
                        MedicalAnalysisRunRecord.source_hash == DocumentRecord.file_hash,
                        MedicalAnalysisRunRecord.parsed_source_hash == DocumentRecord.parsed_source_hash,
                        DocumentRecord.parsed_source_hash.is_not(None),
                        DocumentRecord.parsed_source_hash != "",
                        MedicalAnalysisResultRecord.validation_status == "validated",
                    )
                    .order_by(
                        MedicalAnalysisRunRecord.document_id,
                        MedicalAnalysisRunRecord.created_at.desc(),
                        MedicalAnalysisRunRecord.id,
                    )
                ).all()
                runs_by_document: dict[str, tuple[Any, Any]] = {}
                for run, result in current_rows:
                    if run.document_id in runs_by_document:
                        raise DiseaseProfileError(
                            "A selected document has multiple current analyses.",
                            code="comparison_source_changed",
                            status_code=409,
                        )
                    runs_by_document[run.document_id] = (run, result)

                missing_runs = set(documents) - set(runs_by_document)
                if missing_runs:
                    raise DiseaseProfileError(
                        "A selected document no longer has a current validated analysis.",
                        code="comparison_source_changed",
                        status_code=409,
                    )

                evidence_by_run = self._load_evidence(
                    db,
                    [run.id for run, _result in runs_by_document.values()],
                )
                records_by_document: dict[str, dict[str, Any]] = {}
                for document_id, document in documents.items():
                    run, result = runs_by_document[document_id]
                    report = _normalize_comparison_report(
                        result.report_json,
                        row_schema_version=run.schema_version,
                    )
                    if report is None:
                        raise DiseaseProfileError(
                            "A selected document has an invalid analysis report.",
                            code="comparison_report_invalid",
                            status_code=409,
                        )
                    records_by_document[document_id] = {
                        "link": {},
                        "document": document,
                        "analyses": [{
                            "run": _analysis_run_dict(run, result),
                            "report": report,
                            "evidence": evidence_by_run.get(run.id, []),
                            "valid": True,
                            "source_current": True,
                            "warnings": [],
                        }],
                        "matches": [],
                        "questions": [],
                    }
                return [
                    records_by_document[document_id]
                    for document_id in selected_documents
                    if document_id in records_by_document
                ]
        except DiseaseProfileError:
            raise
        except SQLAlchemyError as exc:
            log.warning("Could not load comparison inputs")
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
        limit: int = 20,
        after_document_id: str | None = None,
    ) -> dict[str, Any]:
        """Return one bounded page of classified documents without a link."""
        self._require_available()
        page_size = max(1, min(int(limit), 50))
        try:
            with self.session_factory() as db:
                linked = select(DocumentDiseaseLinkRecord.document_id).where(
                    DocumentDiseaseLinkRecord.user_id == user_id,
                    DocumentDiseaseLinkRecord.workspace_id == workspace_id,
                    DocumentDiseaseLinkRecord.document_id == DocumentRecord.id,
                )
                base_filters = [
                    DocumentRecord.user_id == user_id,
                    DocumentRecord.workspace_id == workspace_id,
                    DocumentRecord.deleted_at.is_(None),
                    MedicalDocumentProfileRecord.user_id == user_id,
                    MedicalDocumentProfileRecord.workspace_id == workspace_id,
                    MedicalDocumentProfileRecord.document_kind != "unknown",
                    ~linked.exists(),
                ]
                statement = (
                    select(DocumentRecord, MedicalDocumentProfileRecord)
                    .join(
                        MedicalDocumentProfileRecord,
                        MedicalDocumentProfileRecord.document_id == DocumentRecord.id,
                    )
                    .where(*base_filters)
                    # The document id is the opaque, stable keyset cursor. A
                    # mutable modified_at sort would make pages overlap when
                    # a document is edited between requests.
                    .order_by(DocumentRecord.id)
                    .limit(page_size + 1)
                )
                if after_document_id:
                    statement = statement.where(DocumentRecord.id > after_document_id)
                rows = db.execute(statement).all()
                page_rows = rows[:page_size]
                total = int(
                    db.scalar(
                        select(func.count(DocumentRecord.id))
                        .select_from(DocumentRecord)
                        .join(
                            MedicalDocumentProfileRecord,
                            MedicalDocumentProfileRecord.document_id == DocumentRecord.id,
                        )
                        .where(*base_filters)
                    )
                    or 0
                )
                items = [
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
                    for document, profile in page_rows
                ]
                return {
                    "items": items,
                    "total": total,
                    "next_cursor": (
                        str(page_rows[-1][0].id)
                        if len(rows) > page_size and page_rows
                        else None
                    ),
                }
        except SQLAlchemyError as exc:
            log.warning("Could not list unassigned disease documents")
            raise DiseaseProfileError(
                "Disease profile data is temporarily unavailable.",
                code="disease_profile_storage_unavailable",
                status_code=503,
            ) from exc

    def list_profile_documents(
        self,
        *,
        user_id: str,
        workspace_id: str,
        concept_id: str,
        limit: int = 20,
        after_document_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Page the live source documents linked to one disease profile."""
        self._require_available()
        page_size = max(1, min(int(limit), 50))
        try:
            with self.session_factory() as db:
                statement = (
                    select(DocumentDiseaseLinkRecord, DocumentRecord)
                    .join(
                        DocumentRecord,
                        DocumentRecord.id == DocumentDiseaseLinkRecord.document_id,
                    )
                    .where(
                        DocumentDiseaseLinkRecord.user_id == user_id,
                        DocumentDiseaseLinkRecord.workspace_id == workspace_id,
                        DocumentDiseaseLinkRecord.concept_id == concept_id,
                        DocumentRecord.user_id == user_id,
                        DocumentRecord.workspace_id == workspace_id,
                        DocumentRecord.deleted_at.is_(None),
                    )
                    .order_by(DocumentRecord.id)
                    .limit(page_size + 1)
                )
                if after_document_id:
                    statement = statement.where(DocumentRecord.id > after_document_id)
                rows = db.execute(statement).all()
                if not rows:
                    profile_exists = db.scalar(
                        select(DocumentDiseaseLinkRecord.id)
                        .join(
                            DocumentRecord,
                            DocumentRecord.id == DocumentDiseaseLinkRecord.document_id,
                        )
                        .where(
                            DocumentDiseaseLinkRecord.user_id == user_id,
                            DocumentDiseaseLinkRecord.workspace_id == workspace_id,
                            DocumentDiseaseLinkRecord.concept_id == concept_id,
                            DocumentRecord.user_id == user_id,
                            DocumentRecord.workspace_id == workspace_id,
                            DocumentRecord.deleted_at.is_(None),
                        )
                        .limit(1)
                    )
                    return (
                        {"items": [], "next_cursor": None}
                        if profile_exists
                        else None
                    )
                page_rows = rows[:page_size]
                items = self._document_views_for_rows(
                    db,
                    page_rows,
                    user_id=user_id,
                    workspace_id=workspace_id,
                )
                return {
                    "items": items,
                    "next_cursor": (
                        str(page_rows[-1][1].id)
                        if len(rows) > page_size and page_rows
                        else None
                    ),
                }
        except SQLAlchemyError as exc:
            log.warning("Could not page disease profile documents")
            raise DiseaseProfileError(
                "Disease profile data is temporarily unavailable.",
                code="disease_profile_storage_unavailable",
                status_code=503,
            ) from exc

    def list_external_source_documents(
        self,
        *,
        user_id: str,
        workspace_id: str,
        concept_id: str,
        source: str,
        external_id: str,
        limit: int = 20,
        after_document_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Page documents that link one external article to current evidence.

        The joins deliberately require a current validated analysis. This
        prevents an article cached in another workspace, an old analysis, or
        a stale match run from becoming a source for the selected profile.
        """
        self._require_available()
        page_size = max(1, min(int(limit), 50))
        normalized_source = source.strip().lower()
        normalized_external_id = external_id.strip()
        if not normalized_source or not normalized_external_id:
            return {"items": [], "next_cursor": None}
        try:
            with self.session_factory() as db:
                current_run = aliased(MedicalAnalysisRunRecord)
                current_result = aliased(MedicalAnalysisResultRecord)
                candidate_statement = (
                    select(DocumentRecord.id, current_result.report_json)
                    .join(
                        DocumentDiseaseLinkRecord,
                        DocumentDiseaseLinkRecord.document_id == DocumentRecord.id,
                    )
                    .join(
                        LiteratureMatchRunRecord,
                        LiteratureMatchRunRecord.document_id == DocumentRecord.id,
                    )
                    .join(
                        LiteratureSearchRunRecord,
                        LiteratureSearchRunRecord.id == LiteratureMatchRunRecord.search_run_id,
                    )
                    .join(
                        LiteratureEvidenceMatchRecord,
                        LiteratureEvidenceMatchRecord.match_run_id == LiteratureMatchRunRecord.id,
                    )
                    .join(
                        LiteratureArticleRecord,
                        LiteratureArticleRecord.id == LiteratureEvidenceMatchRecord.article_id,
                    )
                    .join(
                        current_run,
                        current_run.id == LiteratureMatchRunRecord.analysis_run_id,
                    )
                    .join(current_result, current_result.run_id == current_run.id)
                    .where(
                        DocumentDiseaseLinkRecord.user_id == user_id,
                        DocumentDiseaseLinkRecord.workspace_id == workspace_id,
                        DocumentDiseaseLinkRecord.concept_id == concept_id,
                        DocumentRecord.user_id == user_id,
                        DocumentRecord.workspace_id == workspace_id,
                        DocumentRecord.deleted_at.is_(None),
                        LiteratureMatchRunRecord.user_id == user_id,
                        LiteratureMatchRunRecord.workspace_id == workspace_id,
                        LiteratureMatchRunRecord.status == "completed",
                        LiteratureSearchRunRecord.user_id == user_id,
                        LiteratureSearchRunRecord.workspace_id == workspace_id,
                        LiteratureSearchRunRecord.status == "succeeded",
                        LiteratureArticleRecord.source == normalized_source,
                        LiteratureArticleRecord.external_id == normalized_external_id,
                        current_run.user_id == user_id,
                        current_run.workspace_id == workspace_id,
                        current_run.document_id == DocumentRecord.id,
                        current_run.status == "succeeded",
                        current_run.is_current.is_(True),
                        current_run.source_hash == DocumentRecord.file_hash,
                        current_run.parsed_source_hash == DocumentRecord.parsed_source_hash,
                        DocumentRecord.parsed_source_hash.is_not(None),
                        DocumentRecord.parsed_source_hash != "",
                        current_result.validation_status == "validated",
                    )
                    .distinct()
                )
                # A valid page is based on the same report-object rule used by
                # load_profile_inputs(), not just the SQL status columns. Scan
                # bounded keyset batches so malformed or empty reports do not
                # consume page slots or hide later valid documents.
                scan_size = max(page_size + 1, 50)
                scan_after = after_document_id
                valid_ids: list[str] = []
                seen_ids: set[str] = set()
                while len(valid_ids) <= page_size:
                    statement = candidate_statement
                    if scan_after:
                        statement = statement.where(DocumentRecord.id > scan_after)
                    statement = statement.order_by(DocumentRecord.id).limit(scan_size)
                    candidate_rows = db.execute(statement).all()
                    if not candidate_rows:
                        break
                    for document_id, report_json in candidate_rows:
                        document_id = str(document_id)
                        if document_id in seen_ids:
                            continue
                        seen_ids.add(document_id)
                        if isinstance(_loads_json(report_json, None), dict):
                            valid_ids.append(document_id)
                            if len(valid_ids) > page_size:
                                break
                    scan_after = str(candidate_rows[-1][0])
                    if len(valid_ids) > page_size or len(candidate_rows) < scan_size:
                        break

                if not valid_ids:
                    source_exists = db.scalar(
                        select(DocumentRecord.id)
                        .join(
                            DocumentDiseaseLinkRecord,
                            DocumentDiseaseLinkRecord.document_id == DocumentRecord.id,
                        )
                        .join(
                            LiteratureMatchRunRecord,
                            LiteratureMatchRunRecord.document_id == DocumentRecord.id,
                        )
                        .join(
                            LiteratureSearchRunRecord,
                            LiteratureSearchRunRecord.id == LiteratureMatchRunRecord.search_run_id,
                        )
                        .join(
                            LiteratureEvidenceMatchRecord,
                            LiteratureEvidenceMatchRecord.match_run_id == LiteratureMatchRunRecord.id,
                        )
                        .join(
                            LiteratureArticleRecord,
                            LiteratureArticleRecord.id == LiteratureEvidenceMatchRecord.article_id,
                        )
                        .where(
                            DocumentDiseaseLinkRecord.user_id == user_id,
                            DocumentDiseaseLinkRecord.workspace_id == workspace_id,
                            DocumentDiseaseLinkRecord.concept_id == concept_id,
                            DocumentRecord.user_id == user_id,
                            DocumentRecord.workspace_id == workspace_id,
                            DocumentRecord.deleted_at.is_(None),
                            LiteratureMatchRunRecord.user_id == user_id,
                            LiteratureMatchRunRecord.workspace_id == workspace_id,
                            LiteratureMatchRunRecord.status == "completed",
                            LiteratureSearchRunRecord.user_id == user_id,
                            LiteratureSearchRunRecord.workspace_id == workspace_id,
                            LiteratureSearchRunRecord.status == "succeeded",
                            LiteratureArticleRecord.source == normalized_source,
                            LiteratureArticleRecord.external_id == normalized_external_id,
                        )
                        .limit(1)
                    )
                    return (
                        {"items": [], "next_cursor": None}
                        if source_exists
                        else None
                    )

                page_ids = valid_ids[:page_size]
                link_rows = db.execute(
                    select(DocumentDiseaseLinkRecord, DocumentRecord)
                    .join(
                        DocumentRecord,
                        DocumentRecord.id == DocumentDiseaseLinkRecord.document_id,
                    )
                    .where(
                        DocumentDiseaseLinkRecord.user_id == user_id,
                        DocumentDiseaseLinkRecord.workspace_id == workspace_id,
                        DocumentDiseaseLinkRecord.concept_id == concept_id,
                        DocumentRecord.user_id == user_id,
                        DocumentRecord.workspace_id == workspace_id,
                        DocumentRecord.id.in_(page_ids),
                        DocumentRecord.deleted_at.is_(None),
                    )
                ).all()
                by_id = {document.id: (link, document) for link, document in link_rows}
                ordered_rows = [by_id[document_id] for document_id in page_ids if document_id in by_id]
                return {
                    "items": self._document_views_for_rows(
                        db,
                        ordered_rows,
                        user_id=user_id,
                        workspace_id=workspace_id,
                    ),
                    "next_cursor": (
                        page_ids[-1]
                        if len(valid_ids) > page_size and page_ids
                        else None
                    ),
                }
        except SQLAlchemyError as exc:
            log.warning("Could not page external source documents")
            raise DiseaseProfileError(
                "Disease profile data is temporarily unavailable.",
                code="disease_profile_storage_unavailable",
                status_code=503,
            ) from exc

    def _document_views_for_rows(
        self,
        db,
        rows: Sequence[tuple[DocumentDiseaseLinkRecord, DocumentRecord]],
        *,
        user_id: str,
        workspace_id: str,
    ) -> list[dict[str, Any]]:
        """Build bounded document views with one batched analysis lookup."""
        documents = {document.id: _document_dict(document) for _link, document in rows}
        document_ids = list(documents)
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
        analyses_by_document: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for run, result in analysis_rows:
            document = documents.get(run.document_id)
            if not document:
                continue
            report = _loads_json(result.report_json, None) if result else None
            source_current = is_current_valid_analysis(run, result, document)
            report_valid = isinstance(report, dict)
            analyses_by_document[run.document_id].append(
                {
                    "run": _analysis_run_dict(run, result),
                    "valid": bool(source_current and report_valid),
                    "warnings": [
                        "analysis_report_unavailable"
                    ] if source_current and not report_valid else [],
                }
            )
        result: list[dict[str, Any]] = []
        seen: set[str] = set()
        for _link, document in rows:
            if document.id in seen:
                continue
            seen.add(document.id)
            analyses = analyses_by_document.get(document.id, [])
            if any(item.get("valid") for item in analyses):
                source_status = "current"
            elif any(
                str((item.get("run") or {}).get("status") or "") == "succeeded"
                for item in analyses
            ):
                source_status = "outdated"
            else:
                source_status = "unavailable"
            document_view = documents[document.id]
            result.append(
                {
                    "document_id": document_view["document_id"],
                    "title": document_view["title"],
                    "document_kind": document_view["document_kind"],
                    "language": document_view["language"],
                    "document_date": document_view["document_date"],
                    "parsed_source_hash": document_view["parsed_source_hash"],
                    "source_status": source_status,
                    "warnings": _unique_strings(
                        warning
                        for item in analyses
                        for warning in item.get("warnings") or []
                    )[:20],
                }
            )
        return result

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
        # This is the storage/API filename accepted by the scoped open route;
        # never expose file_path or any other server filesystem location.
        "open_filename": (row.filename or row.stored_filename or "")[:255],
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


def _normalize_comparison_report(
    report_json: str | None,
    *,
    row_schema_version: str | None,
) -> dict[str, Any] | None:
    """Validate a saved report while preserving raw coverage provenance."""
    raw = _loads_json(report_json, None)
    if not isinstance(raw, Mapping):
        return None
    raw_schema_version = str(raw.get("schema_version") or "").strip()
    stored_schema_version = str(row_schema_version or "").strip()
    if raw_schema_version and stored_schema_version and raw_schema_version != stored_schema_version:
        return None
    candidate_schema_version = raw_schema_version or stored_schema_version
    if candidate_schema_version and candidate_schema_version not in {"medical-insights-v2", "medical-insights-v3"}:
        return None
    try:
        report = MedicalInsightReport.model_validate(dict(raw))
    except (ValidationError, TypeError, ValueError):
        return None
    effective_schema_version = candidate_schema_version or report.schema_version
    if effective_schema_version not in {"medical-insights-v2", "medical-insights-v3"}:
        return None
    normalized = report.model_dump()
    normalized["schema_version"] = effective_schema_version
    # Pydantic supplies a complete coverage default for old reports. That is
    # useful for ordinary AI validation, but comparison must not turn a
    # missing raw field into a claim of complete source coverage.
    if "coverage" not in raw:
        normalized.pop("coverage", None)
    elif isinstance(raw.get("coverage"), Mapping):
        normalized["coverage"] = dict(raw["coverage"])
    return normalized


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


def _unique_strings(value: Iterable[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = str(item or "").strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str:
    return value.isoformat() if value else ""


disease_profile_repository = DiseaseProfileRepository()
