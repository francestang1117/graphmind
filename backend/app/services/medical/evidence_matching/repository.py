"""Transactional persistence for local literature evidence matching."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import logging
from typing import Any, Callable, Mapping
import uuid

from app.core.config import settings
from app.core.database import SessionLocal, db_enabled
from app.models.persistence import (
    DocumentRecord,
    LiteratureArticleRecord,
    LiteratureEvidenceMatchRecord,
    LiteratureMatchRunRecord,
    LiteratureSearchResultRecord,
    LiteratureSearchRunRecord,
    MedicalAnalysisEvidenceRecord,
    MedicalAnalysisResultRecord,
    MedicalAnalysisRunRecord,
)
from app.services.medical.ai.models import MedicalInsightReport
from app.services.medical.evidence_matching.exceptions import LiteratureMatchingError
from app.services.medical.evidence_matching.finding_extractor import (
    FindingExtractor,
    extract_report_condition_concepts,
)
from app.services.medical.evidence_matching.matcher import LiteratureCandidateMatcher
from app.services.medical.evidence_matching.models import (
    FindingMatchResult,
    LiteratureMatchResult,
    MatchableFinding,
    StudyCard,
)
from app.services.medical.evidence_matching.study_card_builder import build_study_card

try:
    from sqlalchemy import delete, select
    from sqlalchemy.exc import IntegrityError, SQLAlchemyError
except ImportError:  # pragma: no cover - only before dependencies are installed
    delete = None
    select = None
    IntegrityError = Exception
    SQLAlchemyError = Exception


log = logging.getLogger(__name__)
MATCHER_VERSION = "literature-match-v1"
COMPLETED = "completed"


class EvidenceMatchingRepository:
    """Save a complete local match result inside one user/workspace scope."""

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
            and DocumentRecord
            and LiteratureMatchRunRecord
            and LiteratureEvidenceMatchRecord
            and MedicalAnalysisRunRecord
            and MedicalAnalysisResultRecord
            and MedicalAnalysisEvidenceRecord
            and LiteratureSearchRunRecord
            and LiteratureSearchResultRecord
            and LiteratureArticleRecord
        )

    def create_or_reuse_match_run(
        self,
        *,
        document_id: str,
        user_id: str,
        workspace_id: str,
        analysis_run_id: str,
        search_run_id: str,
        matcher_version: str = MATCHER_VERSION,
    ) -> tuple[dict[str, Any], bool]:
        """Match and save one report/search pair in one database transaction."""
        self._require_available()
        version = str(matcher_version or MATCHER_VERSION).strip()[:64]
        if not version:
            version = MATCHER_VERSION

        try:
            with self.session_factory() as db:
                # All workflows that mutate a document acquire this lock first.
                # The parent lock also makes a soft delete wait for this result.
                document = self._document(
                    db,
                    document_id,
                    user_id,
                    workspace_id,
                    lock=True,
                )
                if not document:
                    raise LiteratureMatchingError(
                        "The document was not found.",
                        code="literature_match_scope_mismatch",
                    )

                analysis = db.scalars(
                    select(MedicalAnalysisRunRecord)
                    .where(
                        MedicalAnalysisRunRecord.id == analysis_run_id,
                        MedicalAnalysisRunRecord.user_id == user_id,
                        MedicalAnalysisRunRecord.workspace_id == workspace_id,
                    )
                    .with_for_update()
                ).first()
                if not analysis:
                    raise LiteratureMatchingError(
                        "The medical analysis was not found.",
                        code="medical_analysis_not_found",
                    )
                if analysis.document_id != document.id:
                    raise LiteratureMatchingError(
                        "The analysis does not belong to this document.",
                        code="literature_match_scope_mismatch",
                    )
                if analysis.status != "succeeded":
                    raise LiteratureMatchingError(
                        "The medical analysis is not complete.",
                        code="medical_analysis_not_ready",
                    )

                result_row = db.get(MedicalAnalysisResultRecord, analysis.id)
                if not result_row or result_row.validation_status != "validated":
                    raise LiteratureMatchingError(
                        "The medical analysis did not pass validation.",
                        code="medical_analysis_not_validated",
                    )

                search = db.scalars(
                    select(LiteratureSearchRunRecord)
                    .where(
                        LiteratureSearchRunRecord.id == search_run_id,
                        LiteratureSearchRunRecord.user_id == user_id,
                        LiteratureSearchRunRecord.workspace_id == workspace_id,
                    )
                    .with_for_update()
                ).first()
                if not search:
                    raise LiteratureMatchingError(
                        "The literature search was not found.",
                        code="literature_search_not_found",
                    )
                if search.document_id != document.id:
                    raise LiteratureMatchingError(
                        "The literature search does not belong to this document.",
                        code="literature_match_scope_mismatch",
                    )
                if search.status != "succeeded":
                    raise LiteratureMatchingError(
                        "The literature search is not complete.",
                        code="literature_search_not_ready",
                    )

                evidence_rows = db.scalars(
                    select(MedicalAnalysisEvidenceRecord)
                    .where(MedicalAnalysisEvidenceRecord.run_id == analysis.id)
                ).all()
                valid_evidence_ids = {
                    value
                    for row in evidence_rows
                    for value in (row.id, row.evidence_id)
                    if value
                }
                evidence_text_by_id = {
                    value: row.quoted_text
                    for row in evidence_rows
                    for value in (row.id, row.evidence_id)
                    if value
                }
                report = _load_report(result_row.report_json)
                detected_concepts = _loads_json(search.detected_concepts_json, [])
                ontology = _load_optional_ontology()
                analysis_concepts = extract_report_condition_concepts(
                    report,
                    ontology=ontology,
                    evidence_texts=evidence_text_by_id.values(),
                )
                findings = FindingExtractor(
                    ontology=ontology,
                    max_findings=settings.LITERATURE_MATCH_MAX_FINDINGS,
                ).extract(
                    report,
                    analysis_concepts=analysis_concepts,
                    candidate_concepts=detected_concepts,
                    evidence_text_by_id=evidence_text_by_id,
                    valid_evidence_ids=valid_evidence_ids,
                )
                if not findings:
                    raise LiteratureMatchingError(
                        "The report contains no evidence-backed findings to match.",
                        code="literature_match_no_findings",
                    )

                result_rows = db.execute(
                    select(LiteratureSearchResultRecord, LiteratureArticleRecord)
                    .join(
                        LiteratureArticleRecord,
                        LiteratureArticleRecord.id == LiteratureSearchResultRecord.article_id,
                    )
                    .where(LiteratureSearchResultRecord.search_run_id == search.id)
                    .order_by(
                        LiteratureSearchResultRecord.provider_rank.asc(),
                        LiteratureArticleRecord.external_id.asc(),
                    )
                    .limit(max(1, min(int(settings.LITERATURE_MATCH_MAX_ARTICLES), 50)))
                ).all()
                articles = []
                article_rows_by_id: dict[str, LiteratureArticleRecord] = {}
                for result_item, article_row in result_rows:
                    article = _article_dict(article_row)
                    article["provider_rank"] = result_item.provider_rank
                    articles.append(article)
                    article_rows_by_id[article_row.id] = article_row

                matcher = LiteratureCandidateMatcher(
                    min_score=settings.LITERATURE_MATCH_MIN_SCORE,
                    min_condition_score=settings.LITERATURE_MATCH_MIN_CONDITION_SCORE,
                    max_articles=settings.LITERATURE_MATCH_MAX_ARTICLES,
                    max_per_finding=settings.LITERATURE_MATCH_MAX_PER_FINDING,
                    quote_length=settings.LITERATURE_MATCH_ABSTRACT_QUOTE_LENGTH,
                )
                matching = matcher.match(findings, articles)
                fingerprint = _input_fingerprint(
                    analysis=analysis,
                    result_row=result_row,
                    search=search,
                    article_rows=result_rows,
                    matcher_version=version,
                )

                row = db.scalars(
                    select(LiteratureMatchRunRecord)
                    .where(
                        LiteratureMatchRunRecord.user_id == user_id,
                        LiteratureMatchRunRecord.workspace_id == workspace_id,
                        LiteratureMatchRunRecord.analysis_run_id == analysis.id,
                        LiteratureMatchRunRecord.search_run_id == search.id,
                        LiteratureMatchRunRecord.matcher_version == version,
                    )
                    .with_for_update()
                ).first()
                if row and row.input_fingerprint == fingerprint and row.status == COMPLETED:
                    db.commit()
                    return _match_run_payload(db, row), False

                now = _utc_now()
                if row:
                    db.execute(
                        delete(LiteratureEvidenceMatchRecord).where(
                            LiteratureEvidenceMatchRecord.match_run_id == row.id
                        )
                    )
                    row.input_fingerprint = fingerprint
                    row.updated_at = now
                    recomputed = True
                else:
                    row = LiteratureMatchRunRecord(
                        id=uuid.uuid4().hex,
                        user_id=user_id,
                        workspace_id=workspace_id,
                        document_id=document.id,
                        analysis_run_id=analysis.id,
                        search_run_id=search.id,
                        matcher_version=version,
                        input_fingerprint=fingerprint,
                        created_at=now,
                        updated_at=now,
                    )
                    db.add(row)
                    db.flush()
                    recomputed = False

                row.status = COMPLETED
                row.finding_count = len(matching.findings)
                row.article_count = matching.article_count
                row.match_count = matching.match_count
                row.findings_json = _dump_json(_finding_snapshots(matching.findings))
                row.excluded_articles_json = _dump_json(matching.excluded_articles)
                row.warnings_json = _dump_json(matching.warnings)
                row.empty_reason = matching.empty_reason
                row.updated_at = now

                for finding_result in matching.findings:
                    for candidate_rank, card in enumerate(finding_result.candidates, start=1):
                        article_row = article_rows_by_id.get(card.article_id)
                        if not article_row:
                            # This should only be possible for a malformed cache
                            # row; do not create a citation to a missing article.
                            continue
                        db.add(
                            LiteratureEvidenceMatchRecord(
                                id=uuid.uuid4().hex,
                                match_run_id=row.id,
                                finding_id=finding_result.finding.finding_id,
                                finding_type=finding_result.finding.finding_type,
                                finding_text_snapshot=finding_result.finding.statement,
                                document_evidence_ids_json=_dump_json(
                                    finding_result.finding.evidence_ids
                                ),
                                article_id=article_row.id,
                                article_metadata_hash=article_row.metadata_hash or "",
                                article_snapshot_json=_dump_json(_article_snapshot(article_row)),
                                relevance_score=card.relevance_score,
                                match_specificity=card.match_specificity,
                                matched_terms_json=_dump_json(card.matched_terms),
                                match_features_json=_dump_json(
                                    [feature.model_dump(mode="json") for feature in card.match_features]
                                ),
                                abstract_quote=card.abstract_quote,
                                abstract_character_start=card.abstract_character_start,
                                abstract_character_end=card.abstract_character_end,
                                provider_rank=_provider_rank(articles, card.article_id),
                                candidate_rank=candidate_rank,
                                warnings_json=_dump_json(card.warnings),
                                created_at=now,
                            )
                        )

                db.commit()
                payload = _match_run_payload(db, row)
                if recomputed:
                    payload["recomputed"] = True
                return payload, True if not recomputed else False
        except LiteratureMatchingError:
            raise
        except IntegrityError:
            # The scope/version unique key is the final concurrency guard.
            with self.session_factory() as db:
                row = db.scalars(
                    select(LiteratureMatchRunRecord).where(
                        LiteratureMatchRunRecord.user_id == user_id,
                        LiteratureMatchRunRecord.workspace_id == workspace_id,
                        LiteratureMatchRunRecord.analysis_run_id == analysis_run_id,
                        LiteratureMatchRunRecord.search_run_id == search_run_id,
                        LiteratureMatchRunRecord.matcher_version == version,
                    )
                ).first()
                if row:
                    return _match_run_payload(db, row), False
            raise LiteratureMatchingError(
                "Could not save the literature match.",
                code="literature_match_storage_failed",
            )
        except (SQLAlchemyError, OSError, RuntimeError, ValueError) as exc:
            log.exception("Could not create literature match for %s", document_id)
            raise LiteratureMatchingError(
                "Could not save the literature match.",
                code="literature_match_storage_failed",
            ) from exc

    def get_match_run(
        self,
        match_run_id: str,
        user_id: str,
        workspace_id: str,
    ) -> dict[str, Any] | None:
        """Return a match run only when its document is still live and scoped."""
        self._require_available()
        with self.session_factory() as db:
            row = db.scalars(
                select(LiteratureMatchRunRecord).where(
                    LiteratureMatchRunRecord.id == match_run_id,
                    LiteratureMatchRunRecord.user_id == user_id,
                    LiteratureMatchRunRecord.workspace_id == workspace_id,
                )
            ).first()
            if not row or not self._document(db, row.document_id, user_id, workspace_id):
                return None
            return _match_run_payload(db, row)

    def get_latest_for_document(
        self,
        document_id: str,
        user_id: str,
        workspace_id: str,
    ) -> dict[str, Any] | None:
        """Return the newest completed match inside the document scope."""
        self._require_available()
        with self.session_factory() as db:
            if not self._document(db, document_id, user_id, workspace_id):
                return None
            row = db.scalars(
                select(LiteratureMatchRunRecord)
                .where(
                    LiteratureMatchRunRecord.document_id == document_id,
                    LiteratureMatchRunRecord.user_id == user_id,
                    LiteratureMatchRunRecord.workspace_id == workspace_id,
                    LiteratureMatchRunRecord.status == COMPLETED,
                )
                .order_by(
                    LiteratureMatchRunRecord.updated_at.desc(),
                    LiteratureMatchRunRecord.created_at.desc(),
                )
            ).first()
            return _match_run_payload(db, row) if row else None

    def delete_for_document(
        self,
        document_id: str,
        user_id: str,
        workspace_id: str | None = None,
    ) -> None:
        """Remove document-owned match runs; article cache remains reusable."""
        if not self.available() or not document_id:
            return
        with self.session_factory() as db:
            filters = [
                LiteratureMatchRunRecord.document_id == document_id,
                LiteratureMatchRunRecord.user_id == user_id,
            ]
            if workspace_id is not None:
                filters.append(LiteratureMatchRunRecord.workspace_id == workspace_id)
            run_ids = list(
                db.scalars(select(LiteratureMatchRunRecord.id).where(*filters)).all()
            )
            if run_ids:
                # Keep cleanup correct for legacy SQLite connections where
                # foreign-key enforcement may have been disabled before the
                # current engine hook was installed.
                db.execute(
                    delete(LiteratureEvidenceMatchRecord).where(
                        LiteratureEvidenceMatchRecord.match_run_id.in_(run_ids)
                    )
                )
            db.execute(delete(LiteratureMatchRunRecord).where(*filters))
            db.commit()

    @staticmethod
    def _document(db, document_id: str, user_id: str, workspace_id: str, *, lock: bool = False):
        query = select(DocumentRecord).where(
            DocumentRecord.id == document_id,
            DocumentRecord.user_id == user_id,
            DocumentRecord.workspace_id == workspace_id,
            DocumentRecord.deleted_at.is_(None),
        )
        if lock:
            query = query.with_for_update()
        return db.scalars(query).first()

    def _require_available(self) -> None:
        if not self.available():
            raise LiteratureMatchingError(
                "Literature matching persistence is unavailable.",
                code="literature_match_storage_unavailable",
            )


def _load_report(raw: str) -> MedicalInsightReport:
    try:
        return MedicalInsightReport.model_validate(json.loads(raw or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise LiteratureMatchingError(
            "The saved medical analysis is invalid.",
            code="medical_analysis_not_validated",
        ) from exc


def _load_optional_ontology():
    try:
        from app.services.medical.terminology.loader import get_default_ontology

        return get_default_ontology()
    except Exception:
        # Search runs already contain normalized concept names. A missing local
        # ontology must not cause the local matching of an otherwise valid run
        # to call an external service or fail open.
        return None


def _finding_snapshots(findings: list[FindingMatchResult]) -> list[dict[str, Any]]:
    return [
        {
            "finding": item.finding.model_dump(mode="json"),
            "match_status": item.match_status,
        }
        for item in findings
    ]


def _input_fingerprint(
    *,
    analysis: MedicalAnalysisRunRecord,
    result_row: MedicalAnalysisResultRecord,
    search: LiteratureSearchRunRecord,
    article_rows: list[tuple[LiteratureSearchResultRecord, LiteratureArticleRecord]],
    matcher_version: str,
) -> str:
    try:
        report = json.loads(result_row.report_json or "{}")
    except (TypeError, json.JSONDecodeError):
        report = result_row.report_json or ""
    payload = {
        "analysis_run_id": analysis.id,
        "analysis_report_hash": _sha256_json(report),
        "search_run_id": search.id,
        "query_hash": search.query_hash,
        "articles": [
            {
                "article_id": article.id,
                "metadata_hash": article.metadata_hash or "",
                "provider_rank": result.provider_rank,
            }
            for result, article in article_rows
        ],
        "matcher_version": matcher_version,
        "limits": {
            "max_findings": settings.LITERATURE_MATCH_MAX_FINDINGS,
            "max_articles": settings.LITERATURE_MATCH_MAX_ARTICLES,
            "max_per_finding": settings.LITERATURE_MATCH_MAX_PER_FINDING,
            "min_score": settings.LITERATURE_MATCH_MIN_SCORE,
            "min_condition_score": settings.LITERATURE_MATCH_MIN_CONDITION_SCORE,
            "quote_length": settings.LITERATURE_MATCH_ABSTRACT_QUOTE_LENGTH,
        },
    }
    return _sha256_json(payload)


def _match_run_payload(db, row: LiteratureMatchRunRecord) -> dict[str, Any]:
    snapshots = _loads_json(row.findings_json, [])
    snapshot_by_id: dict[str, dict[str, Any]] = {}
    for snapshot in snapshots if isinstance(snapshots, list) else []:
        if isinstance(snapshot, Mapping):
            finding = snapshot.get("finding")
            if isinstance(finding, Mapping) and finding.get("finding_id"):
                snapshot_by_id[str(finding["finding_id"])] = dict(snapshot)

    records = db.execute(
        select(LiteratureEvidenceMatchRecord, LiteratureArticleRecord)
        .join(
            LiteratureArticleRecord,
            LiteratureArticleRecord.id == LiteratureEvidenceMatchRecord.article_id,
        )
        .where(LiteratureEvidenceMatchRecord.match_run_id == row.id)
        .order_by(
            LiteratureEvidenceMatchRecord.finding_id.asc(),
            LiteratureEvidenceMatchRecord.candidate_rank.asc(),
            LiteratureEvidenceMatchRecord.relevance_score.desc(),
            LiteratureEvidenceMatchRecord.provider_rank.asc(),
            LiteratureArticleRecord.external_id.asc(),
        )
    ).all()
    grouped: dict[str, list[StudyCard]] = {}
    stale = False
    retracted_after_matching = 0
    retracted_by_finding: dict[str, int] = {}
    for match, article in records:
        current_hash = article.metadata_hash or ""
        current_status = str(article.retraction_status or "unknown").strip().lower()
        if current_status in {"retracted", "retraction_notice"}:
            retracted_after_matching += 1
            retracted_by_finding[match.finding_id] = (
                retracted_by_finding.get(match.finding_id, 0) + 1
            )
            stale = True
            continue

        snapshot = _loads_json(match.article_snapshot_json, {})
        snapshot_available = isinstance(snapshot, Mapping) and bool(
            str(snapshot.get("external_id") or snapshot.get("pmid") or "").strip()
        )
        if not snapshot_available:
            snapshot = _article_dict(article)
        snapshot_status = str(snapshot.get("retraction_status") or "unknown").strip().lower()
        is_stale = (
            not snapshot_available
            or current_hash != (match.article_metadata_hash or "")
            or current_status != snapshot_status
        )
        card = build_study_card(
            snapshot,
            relevance_score=match.relevance_score,
            match_specificity=match.match_specificity,
            matched_terms=_loads_json(match.matched_terms_json, []),
            match_reasons=[
                str(feature.get("explanation"))
                for feature in _loads_json(match.match_features_json, [])
                if isinstance(feature, Mapping) and feature.get("explanation")
            ],
            match_features=_loads_json(match.match_features_json, []),
            abstract_quote=match.abstract_quote,
            abstract_character_start=match.abstract_character_start,
            abstract_character_end=match.abstract_character_end,
        )
        saved_warnings = _string_list(_loads_json(match.warnings_json, []), limit=20)
        card.warnings = _unique_strings([*saved_warnings, *card.warnings], limit=20)
        status_warning = _retraction_warning(current_status)
        if status_warning:
            card.warnings = _unique_strings([*card.warnings, status_warning], limit=20)
        if is_stale:
            card.stale = True
            card.warnings = _unique_strings([*card.warnings, "article_metadata_changed"], limit=20)
            stale = True
        grouped.setdefault(match.finding_id, []).append(card)

    findings: list[dict[str, Any]] = []
    ordered_ids = [
        str(snapshot.get("finding", {}).get("finding_id"))
        for snapshot in snapshots
        if isinstance(snapshot, Mapping)
        and isinstance(snapshot.get("finding"), Mapping)
        and snapshot.get("finding", {}).get("finding_id")
    ] if isinstance(snapshots, list) else []
    for finding_id in ordered_ids:
        snapshot = snapshot_by_id.get(finding_id)
        if not snapshot:
            continue
        finding = snapshot["finding"]
        match_status = snapshot.get("match_status", "no_candidates")
        if (
            not grouped.get(finding_id)
            and retracted_by_finding.get(finding_id)
            and match_status in {"matched", "condition_only"}
        ):
            match_status = "no_candidates"
        findings.append(
            {
                "finding_id": finding_id,
                "finding_type": finding.get("finding_type"),
                "statement": finding.get("statement", ""),
                "plain_explanation": finding.get("plain_explanation", ""),
                "document_evidence_ids": finding.get("evidence_ids", []),
                "match_status": match_status,
                "candidates": [card.model_dump(mode="json") for card in grouped.get(finding_id, [])],
            }
        )

    warnings = _string_list(_loads_json(row.warnings_json, []), limit=20)
    if stale and "article_metadata_changed" not in warnings:
        warnings = [*warnings, "article_metadata_changed"]
    excluded = _loads_json(row.excluded_articles_json, {})
    if not isinstance(excluded, dict):
        excluded = {}
    if retracted_after_matching:
        excluded = dict(excluded)
        excluded["retracted_after_matching"] = retracted_after_matching
        if "retracted_after_matching" not in warnings:
            warnings = [*warnings, "retracted_after_matching"]
    visible_match_count = sum(len(cards) for cards in grouped.values())
    empty_reason = row.empty_reason or ""
    if retracted_after_matching and visible_match_count == 0:
        empty_reason = "retracted_after_matching"
    return {
        "match_run_id": row.id,
        "user_id": row.user_id,
        "workspace_id": row.workspace_id,
        "document_id": row.document_id,
        "analysis_run_id": row.analysis_run_id,
        "search_run_id": row.search_run_id,
        "matcher_version": row.matcher_version,
        "input_fingerprint": row.input_fingerprint,
        "status": row.status,
        "finding_count": row.finding_count,
        "article_count": row.article_count,
        "match_count": visible_match_count,
        "summary": {
            "finding_count": row.finding_count,
            "article_count": row.article_count,
            "match_count": visible_match_count,
            "retracted_articles_excluded": int(excluded.get("retracted", 0))
            + int(excluded.get("retraction_notice", 0))
            + int(excluded.get("retracted_after_matching", 0)),
        },
        "excluded_articles": excluded,
        "warnings": warnings,
        "empty_reason": empty_reason,
        "stale": stale,
        "findings": findings,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }


def _article_dict(row: LiteratureArticleRecord) -> dict[str, Any]:
    return {
        "id": row.id,
        "source": row.source,
        "external_id": row.external_id,
        "doi": row.doi,
        "pmcid": row.pmcid,
        "title": row.title,
        "abstract": row.abstract,
        "journal": row.journal,
        "publication_date": row.publication_date,
        "publication_year": row.publication_year,
        "authors": _loads_json(row.authors_json, []),
        "publication_types": _loads_json(row.publication_types_json, []),
        "mesh_terms": _loads_json(row.mesh_terms_json, []),
        "language": row.language,
        "source_url": row.source_url,
        "retraction_status": row.retraction_status,
        "metadata_hash": row.metadata_hash,
        "fetched_at": row.fetched_at,
    }


def _article_snapshot(row: LiteratureArticleRecord) -> dict[str, Any]:
    """Return JSON-safe public metadata captured at match creation time."""
    snapshot = _article_dict(row)
    fetched_at = snapshot.get("fetched_at")
    if isinstance(fetched_at, datetime):
        snapshot["fetched_at"] = fetched_at.isoformat()
    return snapshot


def _string_list(value: Any, *, limit: int) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return _unique_strings(value, limit=limit)


def _unique_strings(values: Any, *, limit: int) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value or "").strip()
        if item and item not in seen:
            seen.add(item)
            result.append(item)
            if len(result) >= limit:
                break
    return result


def _retraction_warning(status: str) -> str | None:
    if status == "expression_of_concern":
        return "PubMed marks this article with an expression of concern."
    if status in {"corrected", "correction_notice"}:
        return "PubMed indicates that this article has a correction notice."
    if status == "unknown":
        return "The article's publication status is unknown."
    return None


def _provider_rank(articles: list[dict[str, Any]], article_id: str) -> int:
    for article in articles:
        if article.get("id") == article_id:
            try:
                return int(article.get("provider_rank") or 0)
            except (TypeError, ValueError):
                return 0
    return 0


def _dump_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _loads_json(value: str | None, default: Any) -> Any:
    try:
        return json.loads(value or "")
    except (TypeError, json.JSONDecodeError):
        return default


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(_dump_json(value).encode("utf-8")).hexdigest()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str:
    return value.isoformat() if value else ""


evidence_matching_repository = EvidenceMatchingRepository()
