"""Scoped API for evidence-backed medical document insights."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse

from app.api.endpoints.auth import UserRecord, current_user_or_dev
from app.api.workspace_scope import normalize_workspace_id, resolve_workspace_id
from app.core.config import settings
from app.core.errors import AppError
from app.services.document_service import document_service
from app.services.medical.ai.analysis_repository import (
    medical_analysis_repository,
)
from app.services.medical.ai.exceptions import MedicalInsightError
from app.services.medical.ai.provider import get_provider
from app.tasks.medical_analysis import run_medical_analysis_once, run_medical_insight

log = logging.getLogger(__name__)
router = APIRouter()

SUPPORTED_DOCUMENT_KINDS = {"research_paper", "guideline"}


def _user_id(user: UserRecord) -> str:
    return getattr(user, "id", "local-dev")


@router.post("/documents/{document_id}/medical-insights")
async def start_medical_insights(
    document_id: str,
    background_tasks: BackgroundTasks,
    workspace_id: str | None = Query(None),
    user: UserRecord = Depends(current_user_or_dev),
) -> JSONResponse:
    """Queue an analysis, or return the existing run for the same version."""
    return await _start_analysis(
        document_id,
        background_tasks,
        user,
        workspace_id=workspace_id,
        force=False,
    )


@router.post("/documents/{document_id}/medical-insights/reanalyze")
async def reanalyze_medical_insights(
    document_id: str,
    background_tasks: BackgroundTasks,
    workspace_id: str | None = Query(None),
    user: UserRecord = Depends(current_user_or_dev),
) -> JSONResponse:
    """Start a fresh version while keeping the previous successful report."""
    return await _start_analysis(
        document_id,
        background_tasks,
        user,
        workspace_id=workspace_id,
        force=True,
    )


@router.get("/medical-analysis-runs/{run_id}")
async def get_medical_insight_run(
    run_id: str,
    workspace_id: str | None = Query(None),
    user: UserRecord = Depends(current_user_or_dev),
) -> dict[str, Any]:
    """Return a run only inside the caller's workspace."""
    user_id = _user_id(user)
    scope = resolve_workspace_id(user_id, normalize_workspace_id(workspace_id))
    _require_repository()
    run = medical_analysis_repository.get_run(run_id, user_id, scope)
    if not run:
        raise HTTPException(status_code=404, detail="Medical insight run not found")
    return run


@router.get("/documents/{document_id}/medical-insights/latest")
async def get_latest_medical_insights(
    document_id: str,
    workspace_id: str | None = Query(None),
    user: UserRecord = Depends(current_user_or_dev),
) -> dict[str, Any]:
    """Return the latest validated report for the live document version."""
    user_id = _user_id(user)
    scope = resolve_workspace_id(user_id, normalize_workspace_id(workspace_id))
    _get_scoped_document(document_id, user_id, scope)
    _require_repository()
    report = medical_analysis_repository.get_latest(document_id, user_id, scope)
    if not report:
        raise HTTPException(status_code=404, detail="No completed medical insight found")
    return report


@router.get("/documents/{document_id}/medical-insights/current")
async def get_current_medical_insights(
    document_id: str,
    workspace_id: str | None = Query(None),
    user: UserRecord = Depends(current_user_or_dev),
) -> dict[str, Any]:
    """Return the latest run state so the UI can recover after a refresh."""
    user_id = _user_id(user)
    scope = resolve_workspace_id(user_id, normalize_workspace_id(workspace_id))
    _get_scoped_document(document_id, user_id, scope)
    _require_repository()
    run = medical_analysis_repository.get_current(document_id, user_id, scope)
    if not run:
        raise HTTPException(status_code=404, detail="No medical insight run found")
    return run


async def _start_analysis(
    document_id: str,
    background_tasks: BackgroundTasks,
    user: UserRecord,
    *,
    workspace_id: str | None,
    force: bool,
) -> JSONResponse:
    if not settings.MEDICAL_AI_ENABLED:
        raise AppError(
            "Medical insight analysis is disabled.",
            code="medical_insights_disabled",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    user_id = _user_id(user)
    scope = resolve_workspace_id(user_id, normalize_workspace_id(workspace_id))
    metadata = _get_scoped_document(document_id, user_id, scope)
    _require_repository()
    source = medical_analysis_repository.get_source(document_id, user_id, scope)
    if not source:
        raise HTTPException(status_code=404, detail="Document source not found")

    document_kind = source.get("document_kind") or metadata.get("document_kind") or "unknown"
    if document_kind not in SUPPORTED_DOCUMENT_KINDS:
        if document_kind == "unknown":
            raise AppError(
                "Medical document classification is not ready yet.",
                code="analysis_not_ready",
                status_code=status.HTTP_409_CONFLICT,
            )
        raise AppError(
            "This medical document type is not supported yet.",
            code="unsupported_document_kind",
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            details={"document_kind": document_kind},
        )
    if not source.get("chunks"):
        raise AppError(
            "Document parsing is not finished yet.",
            code="analysis_not_ready",
            status_code=status.HTTP_409_CONFLICT,
        )

    provider_name = settings.MEDICAL_AI_PROVIDER.strip().lower()
    try:
        configured_provider = get_provider(provider_name, settings.MEDICAL_AI_MODEL)
    except MedicalInsightError as exc:
        raise AppError(
            "The configured medical AI provider is unavailable.",
            code=exc.code,
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        ) from exc

    try:
        run, created = medical_analysis_repository.create_or_reuse(
            document_id=document_id,
            user_id=user_id,
            workspace_id=scope,
            source_hash=str(source.get("source_hash") or metadata.get("file_hash") or ""),
            requested_by=user_id,
            provider=provider_name,
            model_name=configured_provider.model_name,
            prompt_version=settings.MEDICAL_AI_PROMPT_VERSION,
            schema_version=settings.MEDICAL_AI_SCHEMA_VERSION,
            parsed_source_hash=source.get("parsed_source_hash"),
            redact_pii=settings.MEDICAL_AI_REDACT_PII,
            max_input_tokens=settings.MEDICAL_AI_MAX_INPUT_TOKENS,
            timeout_seconds=settings.MEDICAL_AI_TIMEOUT_SECONDS,
            max_output_tokens=settings.MEDICAL_AI_MAX_OUTPUT_TOKENS,
            provider_retry_count=settings.MEDICAL_AI_PROVIDER_RETRY_COUNT,
            force=force,
        )
    except MedicalInsightError as exc:
        raise AppError(
            str(exc),
            code=exc.code,
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        ) from exc

    if created:
        _enqueue(run["run_id"], background_tasks)

    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED if created else status.HTTP_200_OK,
        content=run,
    )


def _enqueue(run_id: str, background_tasks: BackgroundTasks) -> None:
    """Publish only after the run row exists, so workers can never outrun it."""
    if not settings.CELERY_ENABLED:
        background_tasks.add_task(run_medical_analysis_once, run_id)
        return

    try:
        run_medical_insight.apply_async(args=(run_id,), task_id=run_id)
    except Exception as exc:
        medical_analysis_repository.save_failure(
            run_id,
            "analysis_queue_failed",
            "Could not queue medical insight analysis.",
        )
        log.exception("Could not publish medical insight run %s", run_id)
        raise AppError(
            "Could not start medical insight analysis.",
            code="analysis_queue_failed",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            details={"run_id": run_id},
        ) from exc


def _get_scoped_document(document_id: str, user_id: str, workspace_id: str) -> dict[str, Any]:
    # This endpoint accepts the internal document UUID only. Falling back to a
    # stored filename here would allow a same-user document from another
    # workspace to leak into the requested analysis.
    metadata = document_service.get_document_by_id(
        document_id,
        user_id,
        workspace_id=workspace_id,
    )
    if not metadata:
        raise HTTPException(status_code=404, detail="Document not found")
    return metadata


def _require_repository() -> None:
    if not medical_analysis_repository.available():
        raise AppError(
            "Medical insight persistence is unavailable.",
            code="analysis_storage_unavailable",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
