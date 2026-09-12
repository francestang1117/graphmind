"""Scoped API for matching saved medical findings to saved PubMed results."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.api.endpoints.auth import UserRecord, current_user_or_dev
from app.api.workspace_scope import normalize_workspace_id, resolve_workspace_id
from app.core.config import settings
from app.core.errors import AppError
from app.services.document_service import document_service
from app.services.medical.evidence_matching.exceptions import LiteratureMatchingError
from app.services.medical.evidence_matching.repository import evidence_matching_repository


router = APIRouter()


class LiteratureMatchRequest(BaseModel):
    """The two already-completed local inputs for one match run."""

    analysis_run_id: str = Field(..., min_length=1, max_length=64)
    search_run_id: str = Field(..., min_length=1, max_length=64)


@router.post("/documents/{document_id}/literature-matches")
async def create_literature_match(
    document_id: str,
    body: LiteratureMatchRequest,
    workspace_id: str | None = Query(None),
    user: UserRecord = Depends(current_user_or_dev),
) -> JSONResponse:
    """Create or reuse a local finding-to-PubMed candidate set."""
    _ensure_enabled()
    user_id = _user_id(user)
    scope = resolve_workspace_id(user_id, normalize_workspace_id(workspace_id))
    _get_scoped_document(document_id, user_id, scope)
    try:
        run, created = evidence_matching_repository.create_or_reuse_match_run(
            document_id=document_id,
            user_id=user_id,
            workspace_id=scope,
            analysis_run_id=body.analysis_run_id,
            search_run_id=body.search_run_id,
        )
    except LiteratureMatchingError as exc:
        raise _api_error(exc) from exc

    return JSONResponse(
        status_code=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        content={**run, "created": created},
    )


@router.get("/literature-match-runs/{match_run_id}")
async def get_literature_match(
    match_run_id: str,
    workspace_id: str | None = Query(None),
    user: UserRecord = Depends(current_user_or_dev),
) -> dict[str, Any]:
    """Return one match run without crossing its workspace boundary."""
    _ensure_storage()
    user_id = _user_id(user)
    scope = resolve_workspace_id(user_id, normalize_workspace_id(workspace_id))
    try:
        run = evidence_matching_repository.get_match_run(match_run_id, user_id, scope)
    except LiteratureMatchingError as exc:
        raise _api_error(exc) from exc
    if not run:
        raise HTTPException(status_code=404, detail="Literature match not found")
    return run


@router.get("/documents/{document_id}/literature-matches/latest")
async def get_latest_literature_match(
    document_id: str,
    workspace_id: str | None = Query(None),
    user: UserRecord = Depends(current_user_or_dev),
) -> dict[str, Any]:
    """Return the newest local match result for a live scoped document."""
    _ensure_storage()
    user_id = _user_id(user)
    scope = resolve_workspace_id(user_id, normalize_workspace_id(workspace_id))
    _get_scoped_document(document_id, user_id, scope)
    try:
        run = evidence_matching_repository.get_latest_for_document(
            document_id,
            user_id,
            scope,
        )
    except LiteratureMatchingError as exc:
        raise _api_error(exc) from exc
    if not run:
        raise HTTPException(status_code=404, detail="No literature match found")
    return run


def _user_id(user: UserRecord) -> str:
    return getattr(user, "id", "local-dev")


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
    if not settings.LITERATURE_MATCHING_ENABLED:
        raise AppError(
            "Literature matching is disabled.",
            code="literature_matching_disabled",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    _ensure_storage()


def _ensure_storage() -> None:
    if not evidence_matching_repository.available():
        raise AppError(
            "Literature matching persistence is unavailable.",
            code="literature_match_storage_unavailable",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )


def _api_error(exc: LiteratureMatchingError) -> AppError:
    code = exc.code
    if code.endswith("not_found") or code == "literature_match_scope_mismatch":
        http_status = status.HTTP_404_NOT_FOUND
    elif code.endswith("not_ready") or code.endswith("not_validated"):
        http_status = status.HTTP_409_CONFLICT
    elif code == "literature_match_no_findings":
        http_status = status.HTTP_422_UNPROCESSABLE_ENTITY
    else:
        http_status = status.HTTP_503_SERVICE_UNAVAILABLE
    return AppError(str(exc), code=code, status_code=http_status)

