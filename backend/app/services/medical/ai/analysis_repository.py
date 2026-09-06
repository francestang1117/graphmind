"""Persistence for versioned medical insight runs and their citations."""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from app.core.database import SessionLocal, db_enabled
from app.core.workspace import default_workspace_id
from app.services.medical.ai.citation_validator import evidence_rows
from app.services.medical.ai.exceptions import MedicalInsightError

log = logging.getLogger(__name__)

try:
    from sqlalchemy import delete, select, update
    from sqlalchemy.exc import IntegrityError, SQLAlchemyError
    from app.models.persistence import (
        DocumentSectionRecord,
        DocumentRecord,
        MedicalAnalysisEvidenceRecord,
        MedicalAnalysisResultRecord,
        MedicalAnalysisRunRecord,
        MedicalDocumentProfileRecord,
        ParsedChunkRecord,
    )
except ImportError:  # pragma: no cover - only before DB dependencies are installed
    delete = None
    select = None
    update = None
    IntegrityError = Exception
    SQLAlchemyError = Exception
    DocumentRecord = None  # type: ignore[assignment]
    DocumentSectionRecord = None  # type: ignore[assignment]
    MedicalAnalysisEvidenceRecord = None  # type: ignore[assignment]
    MedicalAnalysisResultRecord = None  # type: ignore[assignment]
    MedicalAnalysisRunRecord = None  # type: ignore[assignment]
    MedicalDocumentProfileRecord = None  # type: ignore[assignment]
    ParsedChunkRecord = None  # type: ignore[assignment]


ANALYSIS_TYPE = "single_document_insight"
QUEUED = "queued"
RUNNING = "running"
SUCCEEDED = "succeeded"
FAILED = "failed"


class AnalysisRepository:
    """Keep report versions and citations inside the document's ownership scope."""

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
            and delete
            and select
            and update
            and DocumentRecord
            and MedicalAnalysisRunRecord
            and MedicalAnalysisResultRecord
            and MedicalAnalysisEvidenceRecord
        )

    def create_or_reuse(
        self,
        *,
        document_id: str,
        user_id: str,
        workspace_id: str,
        source_hash: str,
        requested_by: str,
        provider: str,
        model_name: str,
        prompt_version: str,
        schema_version: str,
        force: bool = False,
    ) -> tuple[dict[str, Any], bool]:
        """Create one queued run, or return the active/successful same version."""
        self._require_available()
        key = _analysis_key(
            document_id,
            source_hash,
            provider,
            model_name,
            prompt_version,
            schema_version,
            force=force,
        )
        now = _utc_now()

        try:
            with self.session_factory() as db:
                document = self._document(db, document_id, user_id, workspace_id)
                if not document:
                    raise MedicalInsightError(
                        "Medical document was not found.",
                        code="document_not_found",
                    )

                row = db.scalars(
                    select(MedicalAnalysisRunRecord)
                    .where(
                        MedicalAnalysisRunRecord.user_id == user_id,
                        MedicalAnalysisRunRecord.workspace_id == workspace_id,
                        MedicalAnalysisRunRecord.document_id == document.id,
                        MedicalAnalysisRunRecord.analysis_key == key,
                    )
                    .with_for_update()
                ).first()
                if row:
                    if row.status in {QUEUED, RUNNING, SUCCEEDED}:
                        return _run_dict(row), False
                    # A failed attempt can be retried without leaving a second
                    # row for the same source and prompt version.
                    _clear_run_payload(db, row.id)
                    row.status = QUEUED
                    row.requested_by = requested_by
                    row.error_code = ""
                    row.error_message = ""
                    row.is_current = False
                    row.created_at = now
                    row.started_at = None
                    row.completed_at = None
                    row.updated_at = now
                    db.commit()
                    return _run_dict(row), True

                row = MedicalAnalysisRunRecord(
                    id=uuid.uuid4().hex,
                    user_id=user_id,
                    workspace_id=workspace_id,
                    document_id=document.id,
                    requested_by=requested_by,
                    status=QUEUED,
                    source_hash=source_hash,
                    analysis_key=key,
                    provider=provider,
                    model_name=model_name,
                    prompt_version=prompt_version,
                    schema_version=schema_version,
                    error_code="",
                    error_message="",
                    is_current=False,
                    created_at=now,
                    updated_at=now,
                )
                db.add(row)
                db.commit()
                return _run_dict(row), True
        except IntegrityError:
            # Two clicks can race between the existence check and INSERT. The
            # unique version key makes one winner authoritative.
            with self.session_factory() as db:
                row = db.scalars(
                    select(MedicalAnalysisRunRecord).where(
                        MedicalAnalysisRunRecord.user_id == user_id,
                        MedicalAnalysisRunRecord.workspace_id == workspace_id,
                        MedicalAnalysisRunRecord.document_id == document_id,
                        MedicalAnalysisRunRecord.analysis_key == key,
                    )
                ).first()
                if row:
                    return _run_dict(row), False
            raise MedicalInsightError(
                "Could not create the medical insight run.",
                code="analysis_storage_failed",
            )
        except MedicalInsightError:
            raise
        except (SQLAlchemyError, OSError, RuntimeError) as exc:
            log.warning("Could not create medical insight run: %s", exc)
            raise MedicalInsightError(
                "Could not create the medical insight run.",
                code="analysis_storage_failed",
            ) from exc

    def mark_running(self, run_id: str) -> dict[str, Any] | None:
        """Claim a queued run so a duplicate delivery cannot run it twice."""
        self._require_available()
        now = _utc_now()
        with self.session_factory() as db:
            row = db.scalars(
                select(MedicalAnalysisRunRecord)
                .where(MedicalAnalysisRunRecord.id == run_id)
                .with_for_update()
            ).first()
            if not row:
                return None
            if row.status != QUEUED:
                return None
            row.status = RUNNING
            row.started_at = row.started_at or now
            row.updated_at = now
            db.commit()
            return _run_dict(row)

    def get_worker_run(self, run_id: str) -> dict[str, Any] | None:
        """Load the run metadata used by a worker; no user input reaches this path."""
        self._require_available()
        with self.session_factory() as db:
            row = db.scalars(
                select(MedicalAnalysisRunRecord).where(MedicalAnalysisRunRecord.id == run_id)
            ).first()
            return _run_dict(row) if row else None

    def save_success(self, run_id: str, output: Any) -> dict[str, Any]:
        """Atomically save a validated report, citations, and current pointer."""
        self._require_available()
        if not output.citations.valid or not output.safety.valid:
            raise MedicalInsightError(
                "Medical insight output did not pass validation.",
                code="failed_validation",
            )

        now = _utc_now()
        try:
            with self.session_factory() as db:
                row = db.scalars(
                    select(MedicalAnalysisRunRecord)
                    .where(MedicalAnalysisRunRecord.id == run_id)
                    .with_for_update()
                ).first()
                if not row:
                    raise MedicalInsightError(
                        "Medical insight run was not found.",
                        code="analysis_not_found",
                    )
                if row.status == SUCCEEDED:
                    # Celery delivery is at-least-once. A duplicate delivery
                    # must return the saved result instead of replacing the
                    # current pointer a second time.
                    return _run_payload(db, row)
                if row.status not in {QUEUED, RUNNING}:
                    raise MedicalInsightError(
                        "Medical insight run is no longer active.",
                        code="analysis_not_active",
                    )
                document = self._document(db, row.document_id, row.user_id, row.workspace_id)
                if not document:
                    raise MedicalInsightError(
                        "The document was deleted before analysis finished.",
                        code="document_deleted",
                    )
                if document.file_hash != row.source_hash:
                    raise MedicalInsightError(
                        "The document changed before analysis finished.",
                        code="source_changed",
                    )

                db.execute(
                    update(MedicalAnalysisRunRecord)
                    .where(
                        MedicalAnalysisRunRecord.user_id == row.user_id,
                        MedicalAnalysisRunRecord.workspace_id == row.workspace_id,
                        MedicalAnalysisRunRecord.document_id == row.document_id,
                        MedicalAnalysisRunRecord.id != row.id,
                        MedicalAnalysisRunRecord.is_current.is_(True),
                    )
                    .values(is_current=False, updated_at=now)
                )
                _clear_run_payload(db, row.id)
                report_json = json.dumps(
                    output.report.model_dump(),
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                warnings_json = json.dumps(output.report.warnings, ensure_ascii=False)
                db.add(
                    MedicalAnalysisResultRecord(
                        run_id=row.id,
                        report_json=report_json,
                        citation_coverage=output.citations.coverage,
                        validation_status="validated",
                        warnings_json=warnings_json,
                        created_at=now,
                    )
                )
                for evidence in evidence_rows(output.report, output.context):
                    db.add(
                        MedicalAnalysisEvidenceRecord(
                            id=_evidence_id(row.id, evidence),
                            evidence_id=evidence["evidence_id"],
                            run_id=row.id,
                            finding_id=evidence["finding_id"],
                            chunk_id=evidence["chunk_id"],
                            section_id=evidence.get("section_id"),
                            section_type=evidence.get("section_type") or "unknown",
                            section_title=evidence.get("section_title") or "",
                            page_start=evidence.get("page_start"),
                            page_end=evidence.get("page_end"),
                            quoted_text=evidence["quoted_text"],
                            character_start=evidence.get("character_start"),
                            character_end=evidence.get("character_end"),
                        )
                    )

                row.status = SUCCEEDED
                row.is_current = True
                row.error_code = ""
                row.error_message = ""
                row.completed_at = now
                row.updated_at = now
                db.commit()
                return _run_payload(db, row)
        except MedicalInsightError:
            raise
        except (SQLAlchemyError, OSError, RuntimeError) as exc:
            log.exception("Could not save medical insight run %s", run_id)
            raise MedicalInsightError(
                "Could not save the medical insight result.",
                code="analysis_storage_failed",
            ) from exc

    def save_failure(self, run_id: str, code: str, message: str) -> None:
        """Record an analysis failure without changing the source document."""
        if not self.available():
            return
        now = _utc_now()
        try:
            with self.session_factory() as db:
                row = db.scalars(
                    select(MedicalAnalysisRunRecord)
                    .where(MedicalAnalysisRunRecord.id == run_id)
                    .with_for_update()
                ).first()
                if not row or row.status == SUCCEEDED:
                    return
                row.status = FAILED
                row.error_code = str(code or "analysis_failed")[:80]
                row.error_message = str(message or "Medical insight analysis failed.")[:1000]
                row.completed_at = now
                row.updated_at = now
                db.commit()
        except (SQLAlchemyError, OSError, RuntimeError):
            log.exception("Could not record medical insight failure %s", run_id)

    def get_run(self, run_id: str, user_id: str, workspace_id: str) -> dict[str, Any] | None:
        """Return a run only when both the run and its live document are in scope."""
        self._require_available()
        with self.session_factory() as db:
            row = db.scalars(
                select(MedicalAnalysisRunRecord).where(
                    MedicalAnalysisRunRecord.id == run_id,
                    MedicalAnalysisRunRecord.user_id == user_id,
                    MedicalAnalysisRunRecord.workspace_id == workspace_id,
                )
            ).first()
            if not row:
                return None
            document = self._document(db, row.document_id, user_id, workspace_id)
            if not document:
                return None
            payload = _run_payload(db, row)
            if row.source_hash != document.file_hash:
                payload["outdated"] = True
                payload["is_current"] = False
            return payload

    def get_latest(self, document_id: str, user_id: str, workspace_id: str) -> dict[str, Any] | None:
        """Return the latest successful report for the current source version."""
        self._require_available()
        with self.session_factory() as db:
            document = self._document(db, document_id, user_id, workspace_id)
            if not document:
                return None
            row = db.scalars(
                select(MedicalAnalysisRunRecord)
                .where(
                    MedicalAnalysisRunRecord.document_id == document.id,
                    MedicalAnalysisRunRecord.user_id == user_id,
                    MedicalAnalysisRunRecord.workspace_id == workspace_id,
                    MedicalAnalysisRunRecord.source_hash == document.file_hash,
                    MedicalAnalysisRunRecord.status == SUCCEEDED,
                    MedicalAnalysisRunRecord.is_current.is_(True),
                )
                .order_by(MedicalAnalysisRunRecord.completed_at.desc())
            ).first()
            return _run_payload(db, row) if row else None

    def get_source(
        self,
        document_id: str,
        user_id: str,
        workspace_id: str,
    ) -> dict[str, Any] | None:
        """Load the live paper data used by a worker, all in one scope."""
        self._require_available()
        with self.session_factory() as db:
            document = self._document(db, document_id, user_id, workspace_id)
            if not document:
                return None

            profile = db.scalars(
                select(MedicalDocumentProfileRecord).where(
                    MedicalDocumentProfileRecord.document_id == document.id,
                    MedicalDocumentProfileRecord.user_id == user_id,
                    MedicalDocumentProfileRecord.workspace_id == workspace_id,
                )
            ).first()
            sections = db.scalars(
                select(DocumentSectionRecord)
                .where(
                    DocumentSectionRecord.document_id == document.id,
                    DocumentSectionRecord.user_id == user_id,
                    DocumentSectionRecord.workspace_id == workspace_id,
                )
                .order_by(DocumentSectionRecord.ordinal)
            ).all()
            chunks = db.scalars(
                select(ParsedChunkRecord)
                .where(
                    ParsedChunkRecord.document_id == document.id,
                    ParsedChunkRecord.user_id == user_id,
                    ParsedChunkRecord.workspace_id == workspace_id,
                )
                .order_by(ParsedChunkRecord.chunk_index)
            ).all()

            return {
                "document_id": document.id,
                "workspace_id": workspace_id,
                "source_hash": document.file_hash,
                "title": document.original_filename,
                "document_kind": (
                    profile.document_kind
                    if profile
                    else document.document_kind or "unknown"
                ),
                "language": (
                    profile.language
                    if profile
                    else document.language or "unknown"
                ),
                "sections": [
                    {
                        "id": item.id,
                        "section_type": item.section_type,
                        "original_title": item.original_title,
                        "ordinal": item.ordinal,
                        "page_start": item.page_start,
                        "page_end": item.page_end,
                        "char_start": item.char_start,
                        "char_end": item.char_end,
                        "text": item.text,
                        "language": item.language,
                        "confidence": item.confidence,
                        "metadata": _loads_json(item.metadata_json, {}),
                    }
                    for item in sections
                ],
                "chunks": [
                    {
                        "id": item.id,
                        "document_id": item.document_id,
                        "user_id": item.user_id,
                        "workspace_id": item.workspace_id,
                        "chunk_index": item.chunk_index,
                        "chunk_type": item.chunk_type,
                        "text": item.text,
                        "metadata": _loads_json(item.metadata_json, {}),
                    }
                    for item in chunks
                ],
            }

    def delete_for_document(self, document_id: str, user_id: str, workspace_id: str | None = None) -> None:
        """Delete reports and citation rows when their source document is removed."""
        if not self.available() or not document_id:
            return
        scope = workspace_id or default_workspace_id(user_id)
        with self.session_factory() as db:
            run_ids = list(
                db.scalars(
                    select(MedicalAnalysisRunRecord.id).where(
                        MedicalAnalysisRunRecord.document_id == document_id,
                        MedicalAnalysisRunRecord.user_id == user_id,
                        MedicalAnalysisRunRecord.workspace_id == scope,
                    )
                ).all()
            )
            if run_ids:
                db.execute(
                    delete(MedicalAnalysisEvidenceRecord).where(
                        MedicalAnalysisEvidenceRecord.run_id.in_(run_ids)
                    )
                )
                db.execute(
                    delete(MedicalAnalysisResultRecord).where(
                        MedicalAnalysisResultRecord.run_id.in_(run_ids)
                    )
                )
                db.execute(
                    delete(MedicalAnalysisRunRecord).where(
                        MedicalAnalysisRunRecord.id.in_(run_ids)
                    )
                )
            db.commit()

    def _document(self, db, document_id: str, user_id: str, workspace_id: str):
        return db.scalars(
            select(DocumentRecord).where(
                DocumentRecord.id == document_id,
                DocumentRecord.user_id == user_id,
                DocumentRecord.workspace_id == workspace_id,
                DocumentRecord.deleted_at.is_(None),
            )
        ).first()

    def _require_available(self) -> None:
        if not self.available():
            raise MedicalInsightError(
                "Medical insight persistence is unavailable.",
                code="analysis_storage_unavailable",
            )


def _analysis_key(
    document_id: str,
    source_hash: str,
    provider: str,
    model_name: str,
    prompt_version: str,
    schema_version: str,
    *,
    force: bool,
) -> str:
    values = [
        ANALYSIS_TYPE,
        document_id,
        source_hash,
        provider,
        model_name,
        prompt_version,
        schema_version,
    ]
    if force:
        values.append(uuid.uuid4().hex)
    return hashlib.sha256("|".join(values).encode("utf-8")).hexdigest()


def _clear_run_payload(db, run_id: str) -> None:
    db.execute(
        delete(MedicalAnalysisEvidenceRecord).where(
            MedicalAnalysisEvidenceRecord.run_id == run_id
        )
    )
    db.execute(
        delete(MedicalAnalysisResultRecord).where(
            MedicalAnalysisResultRecord.run_id == run_id
        )
    )


def _run_payload(db, row: "MedicalAnalysisRunRecord") -> dict[str, Any]:
    payload = _run_dict(row)
    result = db.get(MedicalAnalysisResultRecord, row.id)
    if not result:
        return payload
    payload["report"] = _loads_json(result.report_json, {})
    payload["citation_coverage"] = result.citation_coverage
    payload["validation_status"] = result.validation_status
    payload["warnings"] = _loads_json(result.warnings_json, [])
    evidence = db.scalars(
        select(MedicalAnalysisEvidenceRecord)
        .where(MedicalAnalysisEvidenceRecord.run_id == row.id)
        .order_by(MedicalAnalysisEvidenceRecord.finding_id, MedicalAnalysisEvidenceRecord.id)
    ).all()
    payload["evidence"] = [
        {
            "id": item.id,
            "evidence_id": item.evidence_id or item.id,
            "finding_id": item.finding_id,
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
        for item in evidence
    ]
    return payload


def _run_dict(row: "MedicalAnalysisRunRecord") -> dict[str, Any]:
    return {
        "run_id": row.id,
        "user_id": row.user_id,
        "document_id": row.document_id,
        "workspace_id": row.workspace_id,
        "requested_by": row.requested_by,
        "status": row.status,
        "source_hash": row.source_hash,
        "provider": row.provider,
        "model_name": row.model_name,
        "prompt_version": row.prompt_version,
        "schema_version": row.schema_version,
        "error_code": row.error_code or "",
        "error_message": row.error_message or "",
        "is_current": bool(row.is_current),
        "created_at": _iso(row.created_at),
        "started_at": _iso(row.started_at),
        "completed_at": _iso(row.completed_at),
        "updated_at": _iso(row.updated_at),
    }


def _evidence_id(run_id: str, evidence: dict[str, Any]) -> str:
    raw = f"{run_id}|{evidence['finding_id']}|{evidence['evidence_id']}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _loads_json(value: str, default: Any) -> Any:
    try:
        return json.loads(value or "")
    except (TypeError, json.JSONDecodeError):
        return default


def _iso(value: Optional[datetime]) -> str:
    return value.isoformat() if value else ""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


medical_analysis_repository = AnalysisRepository()
