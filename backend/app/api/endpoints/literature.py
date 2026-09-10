"""Scoped, user-confirmed PubMed search endpoints."""

from __future__ import annotations

from datetime import date
import logging
from typing import Any, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field, model_validator
from fastapi.responses import JSONResponse

from app.api.endpoints.auth import UserRecord, current_user_or_dev
from app.api.workspace_scope import normalize_workspace_id, resolve_workspace_id
from app.core.config import settings
from app.core.errors import AppError
from app.core.rate_limit import literature_limit
from app.services.document_service import document_service
from app.services.medical.literature.exceptions import LiteratureError
from app.services.medical.literature.models import LiteratureQuery
from app.services.medical.literature.pubmed_provider import PubMedProvider
from app.services.medical.literature.query_builder import build_literature_query
from app.services.medical.literature.repository import literature_repository
from app.tasks.literature_search import run_literature_search, run_literature_search_once

log = logging.getLogger(__name__)
router = APIRouter()


class LiteratureSearchRequest(BaseModel):
    """The small set of filters accepted by the first PubMed integration."""

    question: str = Field(..., min_length=1, max_length=500)
    date_from: date | None = None
    date_to: date | None = None
    study_types: list[str] = Field(default_factory=list, max_length=8)
    sort: Literal["relevance", "newest"] = "relevance"
    max_results: int = Field(default=20, ge=1, le=50)
    external_search_confirmed: bool = False
    query_fingerprint: str | None = Field(default=None, min_length=64, max_length=64)

    @model_validator(mode="after")
    def validate_dates(self) -> "LiteratureSearchRequest":
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("date_from must be before date_to")
        return self


def _user_id(user: UserRecord) -> str:
    return getattr(user, "id", "local-dev")


@router.post("/documents/{document_id}/literature-search/preview")
async def preview_literature_search(
    document_id: str,
    body: LiteratureSearchRequest,
    workspace_id: str | None = Query(None),
    user: UserRecord = Depends(current_user_or_dev),
) -> dict[str, Any]:
    """Build the exact safe query before anything is sent to PubMed."""
    _ensure_enabled()
    user_id = _user_id(user)
    scope = resolve_workspace_id(user_id, normalize_workspace_id(workspace_id))
    _get_scoped_document(document_id, user_id, scope)
    query = _build_query(body)
    return _preview_payload(query, document_id, scope)


@router.post("/documents/{document_id}/literature-search")
@literature_limit
async def start_literature_search(
    document_id: str,
    body: LiteratureSearchRequest,
    background_tasks: BackgroundTasks,
    workspace_id: str | None = Query(None),
    user: UserRecord = Depends(current_user_or_dev),
    request: Request = None,
) -> JSONResponse:
    """Create or reuse a confirmed PubMed search and queue its worker."""
    _ensure_enabled()
    user_id = _user_id(user)
    scope = resolve_workspace_id(user_id, normalize_workspace_id(workspace_id))
    _get_scoped_document(document_id, user_id, scope)
    query = _build_query(body)
    _require_confirmation(body, query, document_id, scope)

    provider = PubMedProvider()
    try:
        provider.validate_configuration()
    except LiteratureError as exc:
        raise AppError(
            "The PubMed provider is not configured.",
            code=exc.code,
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        ) from exc

    try:
        run, created = literature_repository.create_or_reuse(
            query=query,
            user_id=user_id,
            workspace_id=scope,
            document_id=document_id,
            external_search_confirmed=True,
        )
    except LiteratureError as exc:
        raise _api_error(exc) from exc

    if created:
        _enqueue(run["run_id"], background_tasks)
    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED if created else status.HTTP_200_OK,
        content={**run, "created": created},
    )


@router.get("/literature-search-runs/{run_id}")
async def get_literature_search(
    run_id: str,
    workspace_id: str | None = Query(None),
    user: UserRecord = Depends(current_user_or_dev),
) -> dict[str, Any]:
    """Return status and results only from the current user's workspace."""
    user_id = _user_id(user)
    scope = resolve_workspace_id(user_id, normalize_workspace_id(workspace_id))
    if not literature_repository.available():
        raise AppError(
            "Literature search persistence is unavailable.",
            code="literature_storage_unavailable",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    try:
        run = literature_repository.get_run(run_id, user_id, scope)
    except LiteratureError as exc:
        raise _api_error(exc) from exc
    if not run:
        raise HTTPException(status_code=404, detail="Literature search not found")
    return run


@router.get("/documents/{document_id}/literature-searches/latest")
async def get_latest_literature_search(
    document_id: str,
    workspace_id: str | None = Query(None),
    user: UserRecord = Depends(current_user_or_dev),
) -> dict[str, Any]:
    """Return the newest search for a document without crossing its scope."""
    user_id = _user_id(user)
    scope = resolve_workspace_id(user_id, normalize_workspace_id(workspace_id))
    _get_scoped_document(document_id, user_id, scope)
    if not literature_repository.available():
        raise AppError(
            "Literature search persistence is unavailable.",
            code="literature_storage_unavailable",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    # The repository exposes only one run by id for status polling. Keeping
    # this query here avoids adding an unbounded result-list API in PR #7.
    run = _latest_run(document_id, user_id, scope)
    if not run:
        raise HTTPException(status_code=404, detail="No literature search found")
    return run


def _build_query(body: LiteratureSearchRequest) -> LiteratureQuery:
    try:
        return build_literature_query(
            body.question,
            date_from=body.date_from,
            date_to=body.date_to,
            study_types=body.study_types,
            sort=body.sort,
            max_results=body.max_results,
        )
    except LiteratureError as exc:
        raise _api_error(
            exc,
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        ) from exc


def _preview_payload(query: LiteratureQuery, document_id: str, workspace_id: str) -> dict[str, Any]:
    return {
        "document_id": document_id,
        "workspace_id": workspace_id,
        "question": query.question,
        "detected_concepts": [item.model_dump() for item in query.detected_concepts],
        "redacted_fields": query.redacted_fields,
        "pubmed_query": query.normalized_query,
        "query_fingerprint": query.query_hash,
        "external_data": {
            "provider": "pubmed",
            "sends_query_terms": True,
            "sends_document_content": False,
            "sends_uploaded_file": False,
            "requires_confirmation": True,
        },
    }


def _require_confirmation(
    body: LiteratureSearchRequest,
    query: LiteratureQuery,
    document_id: str,
    workspace_id: str,
) -> None:
    disclosure = _preview_payload(query, document_id, workspace_id)
    if not body.external_search_confirmed:
        raise AppError(
            "Confirm the PubMed query before starting the external search.",
            code="external_search_confirmation_required",
            status_code=status.HTTP_409_CONFLICT,
            details=disclosure,
        )
    if body.query_fingerprint != query.query_hash:
        raise AppError(
            "The literature query changed. Review and confirm it again.",
            code="external_search_query_changed",
            status_code=status.HTTP_409_CONFLICT,
            details=disclosure,
        )


def _enqueue(run_id: str, background_tasks: BackgroundTasks) -> None:
    """Publish only after the run row exists."""
    if not settings.CELERY_ENABLED:
        background_tasks.add_task(run_literature_search_once, run_id)
        return
    try:
        run_literature_search.apply_async(args=(run_id,), task_id=run_id)
    except Exception as exc:
        literature_repository.save_failure(
            run_id,
            "literature_queue_failed",
            "Could not queue the literature search.",
        )
        log.exception("Could not publish literature search run %s", run_id)
        raise AppError(
            "Could not start the literature search.",
            code="literature_queue_failed",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            details={"run_id": run_id},
        ) from exc


def _get_scoped_document(document_id: str, user_id: str, workspace_id: str) -> dict[str, Any]:
    metadata = document_service.get_document_by_id(
        document_id,
        user_id,
        workspace_id=workspace_id,
    )
    if not metadata:
        raise HTTPException(status_code=404, detail="Document not found")
    return metadata


def _ensure_enabled() -> None:
    if not settings.LITERATURE_SEARCH_ENABLED:
        raise AppError(
            "Literature search is disabled.",
            code="literature_search_disabled",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )


def _api_error(exc: LiteratureError, *, status_code: int | None = None) -> AppError:
    code = exc.code
    if status_code is None:
        status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        if code.startswith("literature_question") or code.startswith("literature_invalid"):
            status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
        elif code.startswith("external_search"):
            status_code = status.HTTP_409_CONFLICT
        elif code.endswith("not_found"):
            status_code = status.HTTP_404_NOT_FOUND
    return AppError(str(exc), code=code, status_code=status_code)


def _latest_run(document_id: str, user_id: str, workspace_id: str) -> dict[str, Any] | None:
    """Read the latest scoped run without exposing a general repository query."""
    from sqlalchemy import select

    from app.core.database import SessionLocal
    from app.models.persistence import LiteratureSearchRunRecord

    with SessionLocal() as db:
        row = db.scalars(
            select(LiteratureSearchRunRecord)
            .where(
                LiteratureSearchRunRecord.document_id == document_id,
                LiteratureSearchRunRecord.user_id == user_id,
                LiteratureSearchRunRecord.workspace_id == workspace_id,
            )
            .order_by(LiteratureSearchRunRecord.created_at.desc())
        ).first()
        if not row:
            return None
        return literature_repository.get_run(row.id, user_id, workspace_id)
