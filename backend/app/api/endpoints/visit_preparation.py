"""Scoped APIs for saving clinician questions and building visit briefs."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.api.endpoints.auth import UserRecord, current_user_or_dev
from app.api.workspace_scope import normalize_workspace_id, resolve_workspace_id
from app.core.errors import AppError
from app.services.medical.visit_preparation.exceptions import VisitPreparationError
from app.services.medical.visit_preparation.models import (
    ClinicianQuestionListView,
    ClinicianQuestionView,
    VisitBriefListView,
    VisitBriefView,
)
from app.services.medical.visit_preparation.service import visit_preparation_service

router = APIRouter()

QuestionStatus = Literal["saved", "asked", "answered", "dismissed"]


class _StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ClinicianQuestionCreateRequest(_StrictRequest):
    analysis_run_id: str = Field(min_length=1, max_length=64)
    suggestion_id: str = Field(min_length=1, max_length=100)


class ClinicianQuestionUpdateRequest(_StrictRequest):
    status: QuestionStatus | None = None
    priority: int | None = Field(default=None, ge=1, le=3)
    user_note: str | None = Field(default=None, max_length=2000)
    expected_version: int = Field(ge=1)

    @model_validator(mode="after")
    def require_a_change(self) -> "ClinicianQuestionUpdateRequest":
        if all(
            value is None
            for value in (self.status, self.priority, self.user_note)
        ):
            raise ValueError("at least one question field must be provided")
        return self


class ClinicianQuestionReorderRequest(_StrictRequest):
    question_id: str = Field(min_length=1, max_length=64)
    target_question_id: str = Field(min_length=1, max_length=64)
    expected_version: int = Field(ge=1)
    target_expected_version: int = Field(ge=1)


class VisitBriefCreateRequest(_StrictRequest):
    question_ids: list[str] = Field(min_length=1, max_length=10)
    include_user_notes: bool = False


@router.post(
    "/workspaces/{workspace_id}/clinician-questions",
    status_code=status.HTTP_201_CREATED,
)
async def save_clinician_question(
    workspace_id: str,
    body: ClinicianQuestionCreateRequest,
    user: UserRecord = Depends(current_user_or_dev),
) -> JSONResponse:
    scope = _scope(user, workspace_id)
    _require_storage()
    try:
        item, created, source_refreshed = visit_preparation_service.save_question(
            user_id=_user_id(user),
            workspace_id=scope,
            analysis_run_id=body.analysis_run_id,
            suggestion_id=body.suggestion_id,
        )
    except VisitPreparationError as exc:
        raise _api_error(exc) from exc
    payload = {
        "item": ClinicianQuestionView.model_validate(item).model_dump(mode="json"),
        "created": created,
        "source_refreshed": source_refreshed,
    }
    return JSONResponse(
        status_code=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        content=payload,
    )


@router.get(
    "/workspaces/{workspace_id}/clinician-questions",
    response_model=ClinicianQuestionListView,
)
async def list_clinician_questions(
    workspace_id: str,
    status_filter: QuestionStatus | None = Query(default=None, alias="status"),
    include_dismissed: bool = Query(default=False),
    limit: int = Query(default=100, ge=1, le=100),
    user: UserRecord = Depends(current_user_or_dev),
) -> ClinicianQuestionListView:
    scope = _scope(user, workspace_id)
    _require_storage()
    try:
        payload = visit_preparation_service.list_questions(
            user_id=_user_id(user),
            workspace_id=scope,
            status=status_filter,
            include_dismissed=include_dismissed,
            limit=limit,
        )
    except VisitPreparationError as exc:
        raise _api_error(exc) from exc
    return ClinicianQuestionListView.model_validate(payload)


@router.patch(
    "/workspaces/{workspace_id}/clinician-questions/reorder",
    response_model=list[ClinicianQuestionView],
)
async def reorder_clinician_questions(
    workspace_id: str,
    body: ClinicianQuestionReorderRequest,
    user: UserRecord = Depends(current_user_or_dev),
) -> list[ClinicianQuestionView]:
    scope = _scope(user, workspace_id)
    _require_storage()
    try:
        items = visit_preparation_service.reorder_questions(
            question_id=body.question_id,
            target_question_id=body.target_question_id,
            user_id=_user_id(user),
            workspace_id=scope,
            expected_version=body.expected_version,
            target_expected_version=body.target_expected_version,
        )
    except VisitPreparationError as exc:
        raise _api_error(exc) from exc
    return [ClinicianQuestionView.model_validate(item) for item in items]


@router.patch(
    "/workspaces/{workspace_id}/clinician-questions/{question_id}",
    response_model=ClinicianQuestionView,
)
async def update_clinician_question(
    workspace_id: str,
    question_id: str,
    body: ClinicianQuestionUpdateRequest,
    user: UserRecord = Depends(current_user_or_dev),
) -> ClinicianQuestionView:
    scope = _scope(user, workspace_id)
    _require_storage()
    try:
        item = visit_preparation_service.update_question(
            question_id,
            user_id=_user_id(user),
            workspace_id=scope,
            status=body.status,
            priority=body.priority,
            user_note=body.user_note,
            expected_version=body.expected_version,
        )
    except VisitPreparationError as exc:
        raise _api_error(exc) from exc
    return ClinicianQuestionView.model_validate(item)


@router.delete(
    "/workspaces/{workspace_id}/clinician-questions/{question_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_clinician_question(
    workspace_id: str,
    question_id: str,
    user: UserRecord = Depends(current_user_or_dev),
) -> Response:
    scope = _scope(user, workspace_id)
    _require_storage()
    try:
        deleted = visit_preparation_service.delete_question(
            question_id,
            user_id=_user_id(user),
            workspace_id=scope,
        )
    except VisitPreparationError as exc:
        raise _api_error(exc) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="Clinician question not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/workspaces/{workspace_id}/visit-briefs",
    response_model=VisitBriefView,
    status_code=status.HTTP_201_CREATED,
)
async def create_visit_brief(
    workspace_id: str,
    body: VisitBriefCreateRequest,
    user: UserRecord = Depends(current_user_or_dev),
) -> VisitBriefView:
    scope = _scope(user, workspace_id)
    _require_storage()
    try:
        brief = visit_preparation_service.create_visit_brief(
            user_id=_user_id(user),
            workspace_id=scope,
            question_ids=body.question_ids,
            include_user_notes=body.include_user_notes,
        )
    except VisitPreparationError as exc:
        raise _api_error(exc) from exc
    return VisitBriefView.model_validate(brief)


@router.get(
    "/workspaces/{workspace_id}/visit-briefs",
    response_model=VisitBriefListView,
)
async def list_visit_briefs(
    workspace_id: str,
    limit: int = Query(default=50, ge=1, le=50),
    user: UserRecord = Depends(current_user_or_dev),
) -> VisitBriefListView:
    scope = _scope(user, workspace_id)
    _require_storage()
    try:
        payload = visit_preparation_service.list_briefs(
            user_id=_user_id(user), workspace_id=scope, limit=limit
        )
    except VisitPreparationError as exc:
        raise _api_error(exc) from exc
    return VisitBriefListView.model_validate(payload)


@router.get(
    "/workspaces/{workspace_id}/visit-briefs/{brief_id}",
    response_model=VisitBriefView,
)
async def get_visit_brief(
    workspace_id: str,
    brief_id: str,
    user: UserRecord = Depends(current_user_or_dev),
) -> VisitBriefView:
    scope = _scope(user, workspace_id)
    _require_storage()
    try:
        brief = visit_preparation_service.get_brief(
            brief_id,
            user_id=_user_id(user),
            workspace_id=scope,
        )
    except VisitPreparationError as exc:
        raise _api_error(exc) from exc
    if not brief:
        raise HTTPException(status_code=404, detail="Visit brief not found")
    return VisitBriefView.model_validate(brief)


@router.delete(
    "/workspaces/{workspace_id}/visit-briefs/{brief_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_visit_brief(
    workspace_id: str,
    brief_id: str,
    user: UserRecord = Depends(current_user_or_dev),
) -> Response:
    scope = _scope(user, workspace_id)
    _require_storage()
    try:
        deleted = visit_preparation_service.delete_brief(
            brief_id,
            user_id=_user_id(user),
            workspace_id=scope,
        )
    except VisitPreparationError as exc:
        raise _api_error(exc) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="Visit brief not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _scope(user: UserRecord, workspace_id: str) -> str:
    return resolve_workspace_id(
        _user_id(user),
        normalize_workspace_id(workspace_id),
    )


def _user_id(user: UserRecord) -> str:
    return getattr(user, "id", "local-dev")


def _require_storage() -> None:
    if not visit_preparation_service.repository.available():
        raise AppError(
            "Visit preparation persistence is unavailable.",
            code="visit_preparation_storage_unavailable",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )


def _api_error(exc: VisitPreparationError) -> AppError:
    if exc.code.endswith("not_found") or exc.code.endswith("scope_mismatch"):
        code_status = status.HTTP_404_NOT_FOUND
    elif exc.code.endswith("conflict") or "outdated" in exc.code or "unavailable" in exc.code:
        code_status = status.HTTP_409_CONFLICT
    elif (
        exc.code.startswith("visit_brief_invalid")
        or exc.code.endswith("dismissed")
        or exc.code.endswith("reorder_invalid")
        or "invalid_status" in exc.code
    ):
        code_status = status.HTTP_422_UNPROCESSABLE_ENTITY
    else:
        code_status = status.HTTP_503_SERVICE_UNAVAILABLE
    return AppError(
        exc.message,
        code=exc.code,
        status_code=code_status,
        details=exc.details,
    )
