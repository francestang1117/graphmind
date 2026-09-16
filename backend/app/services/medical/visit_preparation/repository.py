"""Transactional persistence for clinician questions and visit briefs."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
import re
from typing import Any, Callable, Iterable
import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.exc import SQLAlchemyError

from app.core.database import SessionLocal, db_enabled
from app.core.workspace import default_workspace_id
from app.models.persistence import (
    ClinicianQuestionRecord,
    DocumentRecord,
    MedicalAnalysisEvidenceRecord,
    MedicalAnalysisResultRecord,
    MedicalAnalysisRunRecord,
    VisitBriefItemRecord,
    VisitBriefRecord,
)
from app.services.medical.visit_preparation.exceptions import VisitPreparationError

log = logging.getLogger(__name__)

QUESTION_STATUSES = {"saved", "asked", "answered", "dismissed"}


class VisitPreparationRepository:
    """Keep saved discussion material inside one user/workspace boundary."""

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
            and ClinicianQuestionRecord
            and VisitBriefRecord
            and VisitBriefItemRecord
        )

    def create_or_refresh_question(
        self,
        *,
        user_id: str,
        workspace_id: str,
        source: dict[str, Any],
    ) -> tuple[dict[str, Any], bool, bool]:
        """Save a validated report suggestion, preserving user-owned state."""
        self._require_available()
        source_hash = str(source.get("parsed_source_hash") or "")
        if not source_hash:
            raise VisitPreparationError(
                "The question source is missing a parsed version.",
                code="clinician_question_source_unavailable",
            )

        try:
            with self.session_factory() as db:
                # Serialize source refreshes with document parsing/deletion so
                # a question can never be saved against a mixed source version.
                document = self._locked_document(
                    db,
                    str(source.get("document_id") or ""),
                    user_id,
                    workspace_id,
                )
                if not document:
                    raise VisitPreparationError(
                        "The document was not found.",
                        code="clinician_question_scope_mismatch",
                    )
                if document.parsed_source_hash != source_hash:
                    raise VisitPreparationError(
                        "The document has changed. Refresh the analysis before saving this question.",
                        code="clinician_question_source_outdated",
                    )

                analysis = db.scalars(
                    select(MedicalAnalysisRunRecord)
                    .where(
                        MedicalAnalysisRunRecord.id == str(source.get("analysis_run_id") or ""),
                        MedicalAnalysisRunRecord.user_id == user_id,
                        MedicalAnalysisRunRecord.workspace_id == workspace_id,
                        MedicalAnalysisRunRecord.document_id == document.id,
                    )
                    .with_for_update()
                ).first()
                if not analysis or analysis.status != "succeeded":
                    raise VisitPreparationError(
                        "The medical analysis is not available.",
                        code="clinician_question_analysis_unavailable",
                    )
                if (
                    not analysis.is_current
                    or analysis.parsed_source_hash != document.parsed_source_hash
                ):
                    raise VisitPreparationError(
                        "The medical analysis is out of date. Refresh the analysis before saving this question.",
                        code="clinician_question_source_outdated",
                    )

                category = str(source.get("category") or "")
                topic = str(source.get("topic") or "")
                row = db.scalars(
                    select(ClinicianQuestionRecord)
                    .where(
                        ClinicianQuestionRecord.user_id == user_id,
                        ClinicianQuestionRecord.workspace_id == workspace_id,
                        ClinicianQuestionRecord.document_id == document.id,
                        ClinicianQuestionRecord.category == category,
                        ClinicianQuestionRecord.topic == topic,
                    )
                    .with_for_update()
                ).first()

                now = _utc_now()
                # The topic key makes repeated saves idempotent while the
                # refresh flag tells the API whether the source actually moved.
                if row:
                    changed = _refresh_question_row(row, source, now)
                    if changed:
                        row.version = max(1, row.version or 1) + 1
                        row.updated_at = now
                    db.commit()
                    return _question_dict(db, row), False, changed

                max_position = db.scalar(
                    select(func.max(ClinicianQuestionRecord.position)).where(
                        ClinicianQuestionRecord.user_id == user_id,
                        ClinicianQuestionRecord.workspace_id == workspace_id,
                        ClinicianQuestionRecord.status == "saved",
                    )
                )
                row = ClinicianQuestionRecord(
                    id=uuid.uuid4().hex,
                    user_id=user_id,
                    workspace_id=workspace_id,
                    document_id=document.id,
                    analysis_run_id=str(source["analysis_run_id"]),
                    suggestion_id=str(source["suggestion_id"]),
                    question=str(source["question"]),
                    rationale=str(source.get("rationale") or ""),
                    category=category,
                    topic=topic,
                    source_kind=str(source["source_kind"]),
                    source_id=str(source["source_id"]),
                    evidence_ids_json=_json(source.get("evidence_ids", [])),
                    language=str(source.get("language") or "en"),
                    status="saved",
                    priority=2,
                    position=int(max_position if max_position is not None else -1) + 1,
                    user_note="",
                    version=1,
                    created_at=now,
                    updated_at=now,
                )
                db.add(row)
                db.flush()
                db.commit()
                return _question_dict(db, row), True, False
        except VisitPreparationError:
            raise
        except SQLAlchemyError as exc:
            log.warning("Could not save clinician question: %s", exc)
            raise VisitPreparationError(
                "Could not save the clinician question.",
                code="visit_preparation_storage_failed",
            ) from exc

    def list_questions(
        self,
        *,
        user_id: str,
        workspace_id: str,
        status: str | None = None,
        include_dismissed: bool = False,
        limit: int = 100,
    ) -> dict[str, Any]:
        self._require_available()
        with self.session_factory() as db:
            conditions = self._question_conditions(user_id, workspace_id, status, include_dismissed)
            total = int(db.scalar(select(func.count()).select_from(ClinicianQuestionRecord).where(*conditions)) or 0)
            rows = db.scalars(
                select(ClinicianQuestionRecord)
                .where(*conditions)
                .order_by(
                    ClinicianQuestionRecord.position,
                    ClinicianQuestionRecord.created_at,
                    ClinicianQuestionRecord.id,
                )
                .limit(max(1, min(int(limit or 100), 100)))
            ).all()
            return {"items": [_question_dict(db, row) for row in rows], "total": total}

    def get_question(
        self,
        question_id: str,
        *,
        user_id: str,
        workspace_id: str,
    ) -> dict[str, Any] | None:
        self._require_available()
        with self.session_factory() as db:
            row = db.scalars(
                select(ClinicianQuestionRecord).where(
                    ClinicianQuestionRecord.id == question_id,
                    ClinicianQuestionRecord.user_id == user_id,
                    ClinicianQuestionRecord.workspace_id == workspace_id,
                )
            ).first()
            if not row or not self._live_document(db, row.document_id, user_id, workspace_id):
                return None
            return _question_dict(db, row)

    def update_question(
        self,
        question_id: str,
        *,
        user_id: str,
        workspace_id: str,
        status: str | None,
        priority: int | None,
        position: int | None,
        user_note: str | None,
        expected_version: int,
    ) -> dict[str, Any]:
        self._require_available()
        try:
            with self.session_factory() as db:
                row = db.scalars(
                    select(ClinicianQuestionRecord).where(
                        ClinicianQuestionRecord.id == question_id,
                        ClinicianQuestionRecord.user_id == user_id,
                        ClinicianQuestionRecord.workspace_id == workspace_id,
                    ).with_for_update()
                ).first()
                if not row or not self._live_document(db, row.document_id, user_id, workspace_id):
                    raise VisitPreparationError(
                        "The clinician question was not found.",
                        code="clinician_question_not_found",
                    )
                if row.version != expected_version:
                    raise VisitPreparationError(
                        "The clinician question was changed elsewhere. Reload it and try again.",
                        code="clinician_question_version_conflict",
                    )

                changed = False
                if status is not None:
                    if status not in QUESTION_STATUSES:
                        raise VisitPreparationError(
                            "The question status is invalid.",
                            code="clinician_question_invalid_status",
                        )
                    if row.status != status:
                        row.status = status
                        if position is None:
                            # Status groups are ordered at workspace scope, so
                            # moving a question appends it to the new group.
                            max_position = db.scalar(
                                select(func.max(ClinicianQuestionRecord.position)).where(
                                    ClinicianQuestionRecord.user_id == user_id,
                                    ClinicianQuestionRecord.workspace_id == workspace_id,
                                    ClinicianQuestionRecord.status == status,
                                    ClinicianQuestionRecord.id != row.id,
                                    ClinicianQuestionRecord.document_id.in_(
                                        select(DocumentRecord.id).where(
                                            DocumentRecord.user_id == user_id,
                                            DocumentRecord.workspace_id == workspace_id,
                                            DocumentRecord.deleted_at.is_(None),
                                        )
                                    ),
                                )
                            )
                            row.position = int(max_position if max_position is not None else -1) + 1
                        changed = True
                if priority is not None and row.priority != priority:
                    row.priority = priority
                    changed = True
                if position is not None and row.position != position:
                    row.position = position
                    changed = True
                if user_note is not None:
                    cleaned_note = clean_user_note(user_note)
                    if row.user_note != cleaned_note:
                        row.user_note = cleaned_note
                        changed = True
                if changed:
                    row.version += 1
                    row.updated_at = _utc_now()
                db.commit()
                return _question_dict(db, row)
        except VisitPreparationError:
            raise
        except SQLAlchemyError as exc:
            log.warning("Could not update clinician question %s: %s", question_id, exc)
            raise VisitPreparationError(
                "Could not update the clinician question.",
                code="visit_preparation_storage_failed",
            ) from exc

    def reorder_questions(
        self,
        question_id: str,
        target_question_id: str,
        *,
        user_id: str,
        workspace_id: str,
        expected_version: int,
        target_expected_version: int,
    ) -> list[dict[str, Any]]:
        """Move two questions in one workspace-scoped transaction."""
        self._require_available()
        if question_id == target_question_id:
            raise VisitPreparationError(
                "A question cannot be reordered against itself.",
                code="clinician_question_reorder_invalid",
            )

        try:
            with self.session_factory() as db:
                source = db.scalars(
                    select(ClinicianQuestionRecord).where(
                        ClinicianQuestionRecord.id == question_id,
                        ClinicianQuestionRecord.user_id == user_id,
                        ClinicianQuestionRecord.workspace_id == workspace_id,
                    )
                ).first()
                if not source or not self._live_document(db, source.document_id, user_id, workspace_id):
                    raise VisitPreparationError(
                        "The clinician question was not found.",
                        code="clinician_question_not_found",
                    )

                # Lock the complete status group in a deterministic order.
                # Both reorder directions therefore acquire the same locks.
                live_document_ids = select(DocumentRecord.id).where(
                    DocumentRecord.user_id == user_id,
                    DocumentRecord.workspace_id == workspace_id,
                    DocumentRecord.deleted_at.is_(None),
                )
                rows = db.scalars(
                    select(ClinicianQuestionRecord)
                    .where(
                        ClinicianQuestionRecord.user_id == user_id,
                        ClinicianQuestionRecord.workspace_id == workspace_id,
                        ClinicianQuestionRecord.status == source.status,
                        ClinicianQuestionRecord.document_id.in_(live_document_ids),
                    )
                    .order_by(ClinicianQuestionRecord.position, ClinicianQuestionRecord.id)
                    .with_for_update()
                ).all()
                by_id = {row.id: row for row in rows}
                target = by_id.get(target_question_id)
                source = by_id.get(question_id)
                if not source or not target:
                    raise VisitPreparationError(
                        "Questions must belong to the same status group.",
                        code="clinician_question_reorder_invalid",
                    )
                if source.version != expected_version or target.version != target_expected_version:
                    raise VisitPreparationError(
                        "One or more questions were changed elsewhere. Reload the list and try again.",
                        code="clinician_question_version_conflict",
                    )

                source_index = rows.index(source)
                target_index = rows.index(target)
                rows[source_index], rows[target_index] = rows[target_index], rows[source_index]
                now = _utc_now()
                for position, row in enumerate(rows):
                    if row.position == position:
                        continue
                    row.position = position
                    row.version = max(1, row.version or 1) + 1
                    row.updated_at = now
                db.commit()
                return [_question_dict(db, source), _question_dict(db, target)]
        except VisitPreparationError:
            raise
        except SQLAlchemyError as exc:
            log.warning("Could not reorder clinician questions %s and %s: %s", question_id, target_question_id, exc)
            raise VisitPreparationError(
                "Could not reorder the clinician questions.",
                code="visit_preparation_storage_failed",
            ) from exc

    def delete_question(self, question_id: str, *, user_id: str, workspace_id: str) -> bool:
        self._require_available()
        try:
            with self.session_factory() as db:
                row = db.scalars(
                    select(ClinicianQuestionRecord).where(
                        ClinicianQuestionRecord.id == question_id,
                        ClinicianQuestionRecord.user_id == user_id,
                        ClinicianQuestionRecord.workspace_id == workspace_id,
                    )
                ).first()
                if not row:
                    return False
                db.delete(row)
                db.flush()
                self._delete_empty_briefs(db, user_id=user_id, workspace_id=workspace_id)
                db.commit()
                return True
        except SQLAlchemyError as exc:
            log.warning("Could not delete clinician question %s: %s", question_id, exc)
            raise VisitPreparationError(
                "Could not delete the clinician question.",
                code="visit_preparation_storage_failed",
            ) from exc

    def create_visit_brief(
        self,
        *,
        user_id: str,
        workspace_id: str,
        question_ids: list[str],
        include_user_notes: bool,
    ) -> dict[str, Any]:
        self._require_available()
        if len(question_ids) < 1 or len(question_ids) > 10:
            raise VisitPreparationError(
                "Select between 1 and 10 questions.",
                code="visit_brief_invalid_selection",
            )
        if len(set(question_ids)) != len(question_ids):
            raise VisitPreparationError(
                "A visit brief cannot contain duplicate questions.",
                code="visit_brief_invalid_selection",
            )

        try:
            with self.session_factory() as db:
                rows = db.scalars(
                    select(ClinicianQuestionRecord)
                    .where(
                        ClinicianQuestionRecord.id.in_(question_ids),
                        ClinicianQuestionRecord.user_id == user_id,
                        ClinicianQuestionRecord.workspace_id == workspace_id,
                    )
                    .with_for_update()
                ).all()
                by_id = {row.id: row for row in rows}
                if len(by_id) != len(question_ids):
                    raise VisitPreparationError(
                        "One or more selected questions were not found.",
                        code="visit_brief_question_not_found",
                    )

                ordered_rows = [by_id[item] for item in question_ids]
                for row in ordered_rows:
                    if row.status == "dismissed":
                        raise VisitPreparationError(
                            "Dismissed questions cannot be added to a visit brief.",
                            code="visit_brief_question_dismissed",
                        )
                    source_status = _source_status(db, row)
                    if source_status != "current":
                        raise VisitPreparationError(
                            "A selected question is no longer based on the current analysis.",
                            code="visit_brief_source_outdated",
                        )

                # Copy the question and its evidence in one transaction; the
                # brief must remain stable even when the live question changes.
                now = _utc_now()
                languages = {str(row.language or "en") for row in ordered_rows}
                language = next(iter(languages)) if len(languages) == 1 else "mixed"
                brief = VisitBriefRecord(
                    id=uuid.uuid4().hex,
                    user_id=user_id,
                    workspace_id=workspace_id,
                    status="active",
                    language=language,
                    generated_at=now,
                    data_cutoff_at=now,
                    disclaimer=_disclaimer(language),
                    created_at=now,
                )
                db.add(brief)
                db.flush()
                for position, row in enumerate(ordered_rows):
                    document = _document_for_question(db, row)
                    if not document:
                        raise VisitPreparationError(
                            "A selected question no longer has a source document.",
                            code="visit_brief_source_outdated",
                        )
                    evidence = _snapshot_evidence(db, row)
                    if len(evidence) != len(_loads_list(row.evidence_ids_json)):
                        raise VisitPreparationError(
                            "A selected question no longer has complete source evidence.",
                            code="visit_brief_evidence_unavailable",
                        )
                    db.add(
                        VisitBriefItemRecord(
                            id=uuid.uuid4().hex,
                            visit_brief_id=brief.id,
                            clinician_question_id=row.id,
                            document_id=row.document_id,
                            document_title_snapshot=_document_title(document),
                            document_date_snapshot=str(document.document_date or ""),
                            parsed_source_hash_snapshot=str(document.parsed_source_hash or ""),
                            analysis_run_id=row.analysis_run_id,
                            position=position,
                            question_snapshot=row.question,
                            rationale_snapshot=row.rationale,
                            user_note_snapshot=(clean_user_note(row.user_note) if include_user_notes else ""),
                            evidence_snapshot_json=_json(evidence),
                        )
                    )
                db.commit()
                return _brief_dict(db, brief)
        except VisitPreparationError:
            raise
        except SQLAlchemyError as exc:
            log.warning("Could not create visit brief: %s", exc)
            raise VisitPreparationError(
                "Could not create the visit brief.",
                code="visit_preparation_storage_failed",
            ) from exc

    def list_briefs(self, *, user_id: str, workspace_id: str, limit: int = 50) -> dict[str, Any]:
        self._require_available()
        with self.session_factory() as db:
            conditions = (
                VisitBriefRecord.user_id == user_id,
                VisitBriefRecord.workspace_id == workspace_id,
                VisitBriefRecord.status == "active",
            )
            total = int(db.scalar(select(func.count()).select_from(VisitBriefRecord).where(*conditions)) or 0)
            rows = db.scalars(
                select(VisitBriefRecord)
                .where(*conditions)
                .order_by(VisitBriefRecord.generated_at.desc(), VisitBriefRecord.id.desc())
                .limit(max(1, min(int(limit or 50), 50)))
            ).all()
            return {"items": [_brief_dict(db, row) for row in rows], "total": total}

    def get_brief(self, brief_id: str, *, user_id: str, workspace_id: str) -> dict[str, Any] | None:
        self._require_available()
        with self.session_factory() as db:
            row = db.scalars(
                select(VisitBriefRecord).where(
                    VisitBriefRecord.id == brief_id,
                    VisitBriefRecord.user_id == user_id,
                    VisitBriefRecord.workspace_id == workspace_id,
                    VisitBriefRecord.status == "active",
                )
            ).first()
            return _brief_dict(db, row) if row else None

    def delete_brief(self, brief_id: str, *, user_id: str, workspace_id: str) -> bool:
        self._require_available()
        try:
            with self.session_factory() as db:
                row = db.scalars(
                    select(VisitBriefRecord).where(
                        VisitBriefRecord.id == brief_id,
                        VisitBriefRecord.user_id == user_id,
                        VisitBriefRecord.workspace_id == workspace_id,
                    )
                ).first()
                if not row:
                    return False
                db.delete(row)
                db.commit()
                return True
        except SQLAlchemyError as exc:
            log.warning("Could not delete visit brief %s: %s", brief_id, exc)
            raise VisitPreparationError(
                "Could not delete the visit brief.",
                code="visit_preparation_storage_failed",
            ) from exc

    def delete_for_document(
        self,
        document_id: str,
        *,
        user_id: str,
        workspace_id: str | None = None,
    ) -> None:
        """Remove saved questions and copied source text after a soft delete."""
        if not self.available() or not document_id:
            return
        try:
            with self.session_factory() as db:
                document = db.scalars(
                    select(DocumentRecord).where(
                        DocumentRecord.id == document_id,
                        DocumentRecord.user_id == user_id,
                    )
                ).first()
                # Compatibility delete endpoints may omit workspace_id. The
                # document row remains the authoritative scope after soft delete.
                scope = workspace_id or (
                    document.workspace_id if document and document.workspace_id else default_workspace_id(user_id)
                )
                db.execute(
                    delete(VisitBriefItemRecord).where(
                        VisitBriefItemRecord.document_id == document_id,
                        VisitBriefItemRecord.visit_brief_id.in_(
                            select(VisitBriefRecord.id).where(
                                VisitBriefRecord.user_id == user_id,
                                VisitBriefRecord.workspace_id == scope,
                            )
                        ),
                    )
                )
                db.execute(
                    delete(ClinicianQuestionRecord).where(
                        ClinicianQuestionRecord.document_id == document_id,
                        ClinicianQuestionRecord.user_id == user_id,
                        ClinicianQuestionRecord.workspace_id == scope,
                    )
                )
                self._delete_empty_briefs(db, user_id=user_id, workspace_id=scope)
                db.commit()
        except SQLAlchemyError as exc:
            log.warning("Could not delete visit preparation data for %s: %s", document_id, exc)

    def _question_conditions(
        self,
        user_id: str,
        workspace_id: str,
        status: str | None,
        include_dismissed: bool,
    ) -> tuple[Any, ...]:
        conditions: list[Any] = [
            ClinicianQuestionRecord.user_id == user_id,
            ClinicianQuestionRecord.workspace_id == workspace_id,
            ClinicianQuestionRecord.document_id.in_(
                select(DocumentRecord.id).where(
                    DocumentRecord.user_id == user_id,
                    DocumentRecord.workspace_id == workspace_id,
                    DocumentRecord.deleted_at.is_(None),
                )
            ),
        ]
        if status:
            conditions.append(ClinicianQuestionRecord.status == status)
        elif not include_dismissed:
            conditions.append(ClinicianQuestionRecord.status != "dismissed")
        return tuple(conditions)

    def _locked_document(self, db, document_id: str, user_id: str, workspace_id: str):
        return db.scalars(
            select(DocumentRecord)
            .where(
                DocumentRecord.id == document_id,
                DocumentRecord.user_id == user_id,
                DocumentRecord.workspace_id == workspace_id,
                DocumentRecord.deleted_at.is_(None),
            )
            .with_for_update()
        ).first()

    def _live_document(self, db, document_id: str, user_id: str, workspace_id: str):
        return db.scalars(
            select(DocumentRecord.id).where(
                DocumentRecord.id == document_id,
                DocumentRecord.user_id == user_id,
                DocumentRecord.workspace_id == workspace_id,
                DocumentRecord.deleted_at.is_(None),
            )
        ).first()

    def _require_available(self) -> None:
        if not self.available():
            raise VisitPreparationError(
                "Visit preparation persistence is unavailable.",
                code="visit_preparation_storage_unavailable",
            )

    @staticmethod
    def _delete_empty_briefs(db, *, user_id: str, workspace_id: str) -> None:
        empty_briefs = select(VisitBriefRecord.id).where(
            VisitBriefRecord.user_id == user_id,
            VisitBriefRecord.workspace_id == workspace_id,
            ~select(VisitBriefItemRecord.id)
            .where(VisitBriefItemRecord.visit_brief_id == VisitBriefRecord.id)
            .exists(),
        )
        db.execute(delete(VisitBriefRecord).where(VisitBriefRecord.id.in_(empty_briefs)))


visit_preparation_repository = VisitPreparationRepository()


def _refresh_question_row(row: ClinicianQuestionRecord, source: dict[str, Any], now: datetime) -> bool:
    values = {
        "analysis_run_id": str(source["analysis_run_id"]),
        "suggestion_id": str(source["suggestion_id"]),
        "question": str(source["question"]),
        "rationale": str(source.get("rationale") or ""),
        "source_kind": str(source["source_kind"]),
        "source_id": str(source["source_id"]),
        "evidence_ids_json": _json(source.get("evidence_ids", [])),
        "language": str(source.get("language") or "en"),
    }
    changed = any(getattr(row, key) != value for key, value in values.items())
    for key, value in values.items():
        setattr(row, key, value)
    if changed:
        row.updated_at = now
    return changed


def _question_dict(db, row: ClinicianQuestionRecord) -> dict[str, Any]:
    document = db.scalars(
        select(DocumentRecord).where(
            DocumentRecord.id == row.document_id,
            DocumentRecord.user_id == row.user_id,
            DocumentRecord.workspace_id == row.workspace_id,
        )
    ).first()
    return {
        "id": row.id,
        "workspace_id": row.workspace_id,
        "document_id": row.document_id,
        "document_title": (
            (document.original_filename or document.filename)
            if document
            else "Unavailable document"
        ),
        "analysis_run_id": row.analysis_run_id,
        "suggestion_id": row.suggestion_id,
        "question": row.question,
        "rationale": row.rationale,
        "category": row.category,
        "topic": row.topic,
        "source_kind": row.source_kind,
        "source_id": row.source_id,
        "evidence_ids": _loads_list(row.evidence_ids_json),
        "language": row.language,
        "status": row.status,
        "priority": row.priority,
        "position": row.position,
        "user_note": row.user_note,
        "version": row.version,
        "source_status": _source_status(db, row),
        "evidence": _snapshot_evidence(db, row),
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }


def _brief_dict(db, row: VisitBriefRecord | None) -> dict[str, Any] | None:
    if not row:
        return None
    items = db.scalars(
        select(VisitBriefItemRecord)
        .where(VisitBriefItemRecord.visit_brief_id == row.id)
        .order_by(VisitBriefItemRecord.position, VisitBriefItemRecord.id)
    ).all()
    return {
        "id": row.id,
        "workspace_id": row.workspace_id,
        "status": row.status,
        "language": row.language,
        "generated_at": _iso(row.generated_at),
        "data_cutoff_at": _iso(row.data_cutoff_at),
        "disclaimer": row.disclaimer,
        "items": [
            {
                "id": item.id,
                "clinician_question_id": item.clinician_question_id,
                "document_id": item.document_id,
                "document_title": item.document_title_snapshot or "Unavailable document",
                "document_date": item.document_date_snapshot,
                "parsed_source_hash": item.parsed_source_hash_snapshot,
                "analysis_run_id": item.analysis_run_id,
                "position": item.position,
                "question": item.question_snapshot,
                "rationale": item.rationale_snapshot,
                "user_note": item.user_note_snapshot,
                "evidence": _loads_list(item.evidence_snapshot_json),
            }
            for item in items
        ],
    }


def _source_status(db, row: ClinicianQuestionRecord) -> str:
    # Do not persist this status: it is derived from the live document and
    # analysis so reparsing or deletion is reflected without a background job.
    document = db.scalars(
        select(DocumentRecord).where(
            DocumentRecord.id == row.document_id,
            DocumentRecord.user_id == row.user_id,
            DocumentRecord.workspace_id == row.workspace_id,
            DocumentRecord.deleted_at.is_(None),
        )
    ).first()
    if not document:
        return "unavailable"
    analysis = db.scalars(
        select(MedicalAnalysisRunRecord).where(
            MedicalAnalysisRunRecord.id == row.analysis_run_id,
            MedicalAnalysisRunRecord.user_id == row.user_id,
            MedicalAnalysisRunRecord.workspace_id == row.workspace_id,
            MedicalAnalysisRunRecord.document_id == row.document_id,
        )
    ).first()
    if not analysis:
        return "unavailable"
    result = db.get(MedicalAnalysisResultRecord, analysis.id)
    if not result or result.validation_status != "validated":
        return "unavailable"
    if (
        analysis.status != "succeeded"
        or not analysis.is_current
        or not document.parsed_source_hash
        or analysis.parsed_source_hash != document.parsed_source_hash
    ):
        return "outdated"
    evidence_ids = [
        str(evidence_id)
        for evidence_id in _loads_list(row.evidence_ids_json)
        if str(evidence_id)
    ]
    if not evidence_ids or len(set(evidence_ids)) != len(evidence_ids):
        return "unavailable"
    evidence_count = db.scalar(
        select(func.count(MedicalAnalysisEvidenceRecord.id)).where(
            MedicalAnalysisEvidenceRecord.run_id == analysis.id,
            MedicalAnalysisEvidenceRecord.evidence_id.in_(evidence_ids),
        )
    )
    if int(evidence_count or 0) != len(evidence_ids):
        return "unavailable"
    return "current"


def _document_for_question(db, row: ClinicianQuestionRecord) -> DocumentRecord | None:
    return db.scalars(
        select(DocumentRecord).where(
            DocumentRecord.id == row.document_id,
            DocumentRecord.user_id == row.user_id,
            DocumentRecord.workspace_id == row.workspace_id,
            DocumentRecord.deleted_at.is_(None),
        )
    ).first()


def _document_title(document: DocumentRecord | None) -> str:
    if not document:
        return "Unavailable document"
    return (document.original_filename or document.filename or "Untitled document")[:255]


def _snapshot_evidence(db, row: ClinicianQuestionRecord) -> list[dict[str, Any]]:
    evidence_ids = _loads_list(row.evidence_ids_json)
    if not evidence_ids:
        return []
    rows = db.scalars(
        select(MedicalAnalysisEvidenceRecord).where(
            MedicalAnalysisEvidenceRecord.run_id == row.analysis_run_id,
            MedicalAnalysisEvidenceRecord.evidence_id.in_(evidence_ids),
        )
    ).all()
    by_id = {item.evidence_id: item for item in rows if item.evidence_id}
    snapshot: list[dict[str, Any]] = []
    for evidence_id in evidence_ids:
        item = by_id.get(evidence_id)
        if not item:
            continue
        snapshot.append(
            {
                "evidence_id": evidence_id,
                "chunk_id": item.chunk_id,
                "section_id": item.section_id,
                "section_type": item.section_type,
                "section_title": item.section_title,
                "page_start": item.page_start,
                "page_end": item.page_end,
                "quote": item.quoted_text,
                "character_start": item.character_start,
                "character_end": item.character_end,
            }
        )
    return snapshot


def clean_user_note(value: str) -> str:
    """Keep notes plain text and bounded before they enter a snapshot."""
    cleaned = re.sub(r"<[^>]*>", "", str(value or ""))
    cleaned = "".join(
        character
        for character in cleaned
        if character in "\n\r\t" or ord(character) >= 32
    )
    return cleaned.strip()[:2000]


def _disclaimer(language: str) -> str:
    if language == "zh":
        return "这份就诊准备单仅用于与专业人员讨论，不是诊断或治疗建议。"
    if language == "ja":
        return "この受診準備メモは専門家との相談用であり、診断や治療の助言ではありません。"
    return "This visit preparation sheet is for discussion with a healthcare professional. It is not a diagnosis or treatment recommendation."


def _json(value: Any) -> str:
    return json.dumps(value if isinstance(value, list) else [], ensure_ascii=False, separators=(",", ":"))


def _loads_list(value: str | None) -> list[Any]:
    try:
        parsed = json.loads(value or "[]")
    except (TypeError, json.JSONDecodeError):
        return []
    return parsed if isinstance(parsed, list) else []


def _iso(value: datetime | None) -> str:
    return value.isoformat() if value else ""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)
