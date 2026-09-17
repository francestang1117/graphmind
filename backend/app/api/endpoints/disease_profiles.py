"""Workspace-scoped APIs for disease document links and live profiles."""

from __future__ import annotations

import base64
import binascii

from fastapi import APIRouter, Depends, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field

from app.api.endpoints.auth import UserRecord, current_user_or_dev
from app.api.workspace_scope import normalize_workspace_id, resolve_workspace_id
from app.core.errors import AppError
from app.services.medical.disease_profile.exceptions import DiseaseProfileError
from app.services.medical.disease_profile.models import (
    DiseaseConceptSearchView,
    DiseaseProfileDetail,
    DiseaseProfileItemsView,
    DiseaseProfileListView,
    DocumentDiseaseLink,
    ProfileSection,
    UnassignedDocumentListView,
)
from app.services.medical.disease_profile.service import disease_profile_service


router = APIRouter()


class _StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DiseaseLinkCreateRequest(_StrictRequest):
    concept_id: str = Field(min_length=1, max_length=160)
    matched_alias: str = Field(default="", max_length=200)
    source_search_run_id: str | None = Field(default=None, max_length=64)


class DiseaseLinkResponse(_StrictRequest):
    link: DocumentDiseaseLink
    created: bool


@router.post(
    "/documents/{document_id}/disease-links",
    response_model=DiseaseLinkResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_disease_link(
    document_id: str,
    body: DiseaseLinkCreateRequest,
    workspace_id: str = Query(min_length=1, max_length=64),
    user: UserRecord = Depends(current_user_or_dev),
) -> DiseaseLinkResponse:
    scope = _scope(user, workspace_id)
    _require_storage()
    try:
        link, created = disease_profile_service.create_link(
            user_id=_user_id(user),
            workspace_id=scope,
            document_id=document_id,
            concept_id=body.concept_id,
            matched_alias=body.matched_alias,
            source_search_run_id=body.source_search_run_id,
        )
    except DiseaseProfileError as exc:
        raise _api_error(exc) from exc
    return DiseaseLinkResponse(
        link=DocumentDiseaseLink.model_validate(link),
        created=created,
    )


@router.delete(
    "/documents/{document_id}/disease-links/{concept_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_disease_link(
    document_id: str,
    concept_id: str,
    workspace_id: str = Query(min_length=1, max_length=64),
    user: UserRecord = Depends(current_user_or_dev),
) -> Response:
    scope = _scope(user, workspace_id)
    _require_storage()
    try:
        deleted = disease_profile_service.delete_link(
            user_id=_user_id(user),
            workspace_id=scope,
            document_id=document_id,
            concept_id=concept_id,
        )
    except DiseaseProfileError as exc:
        raise _api_error(exc) from exc
    if not deleted:
        raise AppError(
            "The disease document link was not found.",
            code="disease_link_not_found",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/disease-profiles/concepts/search",
    response_model=DiseaseConceptSearchView,
)
async def search_disease_concepts(
    q: str = Query(min_length=1, max_length=200),
    limit: int = Query(default=20, ge=1, le=50),
    user: UserRecord = Depends(current_user_or_dev),
) -> DiseaseConceptSearchView:
    # The user dependency keeps this private to the same authenticated app;
    # the actual lookup is local and does not use the user-provided text as an
    # external query.
    _ = user
    try:
        return DiseaseConceptSearchView(
            items=disease_profile_service.search_concepts(q, limit=limit)
        )
    except DiseaseProfileError as exc:
        raise _api_error(exc) from exc


@router.get(
    "/disease-profiles/unassigned-documents",
    response_model=UnassignedDocumentListView,
)
async def list_unassigned_disease_documents(
    workspace_id: str = Query(min_length=1, max_length=64),
    user: UserRecord = Depends(current_user_or_dev),
) -> UnassignedDocumentListView:
    scope = _scope(user, workspace_id)
    _require_storage()
    try:
        items = disease_profile_service.list_unassigned_documents(
            user_id=_user_id(user), workspace_id=scope
        )
    except DiseaseProfileError as exc:
        raise _api_error(exc) from exc
    return UnassignedDocumentListView(items=items)


@router.get(
    "/disease-profiles",
    response_model=DiseaseProfileListView,
)
async def list_disease_profiles(
    workspace_id: str = Query(min_length=1, max_length=64),
    limit: int = Query(default=50, ge=1, le=50),
    cursor: str | None = Query(default=None, max_length=512),
    user: UserRecord = Depends(current_user_or_dev),
) -> DiseaseProfileListView:
    scope = _scope(user, workspace_id)
    _require_storage()
    cursor_value = _decode_cursor(cursor, kind="concept") if cursor else None
    try:
        payload = disease_profile_service.list_profiles(
            user_id=_user_id(user),
            workspace_id=scope,
            limit=limit,
            cursor_concept_id=cursor_value,
        )
    except DiseaseProfileError as exc:
        raise _api_error(exc) from exc
    if payload.get("next_cursor"):
        payload["next_cursor"] = _encode_cursor(str(payload["next_cursor"]))
    return DiseaseProfileListView.model_validate(payload)


@router.get(
    "/disease-profiles/{concept_id}/items",
    response_model=DiseaseProfileItemsView,
)
async def get_disease_profile_items(
    concept_id: str,
    workspace_id: str = Query(min_length=1, max_length=64),
    section: ProfileSection = Query(...),
    limit: int = Query(default=20, ge=1, le=50),
    cursor: str | None = Query(default=None, max_length=512),
    user: UserRecord = Depends(current_user_or_dev),
) -> DiseaseProfileItemsView:
    scope = _scope(user, workspace_id)
    _require_storage()
    offset = _decode_offset(cursor) if cursor else 0
    try:
        payload = disease_profile_service.get_items(
            user_id=_user_id(user),
            workspace_id=scope,
            concept_id=concept_id,
            section=section,
            limit=limit,
            offset=offset,
        )
    except DiseaseProfileError as exc:
        raise _api_error(exc) from exc
    if payload is None:
        raise AppError(
            "The disease profile was not found in this research project.",
            code="disease_profile_not_found",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    next_cursor = None
    if offset + len(payload["items"]) < int(payload["total"]):
        next_cursor = _encode_cursor(str(offset + len(payload["items"])))
    return DiseaseProfileItemsView(
        section=payload["section"],
        items=payload["items"],
        next_cursor=next_cursor,
    )


@router.get(
    "/disease-profiles/{concept_id}",
    response_model=DiseaseProfileDetail,
)
async def get_disease_profile(
    concept_id: str,
    workspace_id: str = Query(min_length=1, max_length=64),
    user: UserRecord = Depends(current_user_or_dev),
) -> DiseaseProfileDetail:
    scope = _scope(user, workspace_id)
    _require_storage()
    try:
        payload = disease_profile_service.get_profile(
            user_id=_user_id(user),
            workspace_id=scope,
            concept_id=concept_id,
        )
    except DiseaseProfileError as exc:
        raise _api_error(exc) from exc
    if payload is None:
        raise AppError(
            "The disease profile was not found in this research project.",
            code="disease_profile_not_found",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    return DiseaseProfileDetail.model_validate(payload)


def _scope(user: UserRecord, workspace_id: str) -> str:
    return resolve_workspace_id(
        _user_id(user),
        normalize_workspace_id(workspace_id),
    )


def _user_id(user: UserRecord) -> str:
    return getattr(user, "id", "local-dev")


def _require_storage() -> None:
    if not disease_profile_service.repository.available():
        raise AppError(
            "Disease profile persistence is unavailable.",
            code="disease_profile_storage_unavailable",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )


def _api_error(exc: DiseaseProfileError) -> AppError:
    return AppError(
        exc.message,
        code=exc.code,
        status_code=exc.status_code,
        details=exc.details,
    )


def _encode_cursor(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode("utf-8")).decode("ascii").rstrip("=")


def _decode_cursor(value: str, *, kind: str) -> str:
    try:
        padded = value + "=" * (-len(value) % 4)
        decoded = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
    except (ValueError, UnicodeError, binascii.Error) as exc:
        raise AppError(
            f"The {kind} cursor is invalid.",
            code="disease_profile_invalid_cursor",
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        ) from exc
    if not decoded or len(decoded) > 160:
        raise AppError(
            f"The {kind} cursor is invalid.",
            code="disease_profile_invalid_cursor",
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    return decoded


def _decode_offset(value: str) -> int:
    decoded = _decode_cursor(value, kind="items")
    try:
        offset = int(decoded)
    except ValueError as exc:
        raise AppError(
            "The items cursor is invalid.",
            code="disease_profile_invalid_cursor",
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        ) from exc
    if offset < 0:
        raise AppError(
            "The items cursor is invalid.",
            code="disease_profile_invalid_cursor",
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    return offset
