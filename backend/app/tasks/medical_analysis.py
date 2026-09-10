"""Background task for one scoped medical insight run."""

from __future__ import annotations

import logging
from typing import Any

from app.core.celery_app import celery_app
from app.core.config import settings
from app.services.medical.ai.analyzer import MedicalInsightAnalyzer
from app.services.medical.ai.exceptions import MedicalInsightError
from app.services.medical.ai.analysis_repository import (
    FAILED,
    RUNNING,
    SUCCEEDED,
    medical_analysis_repository,
)
from app.services.medical.ai.provider import get_provider

log = logging.getLogger(__name__)


def run_medical_analysis_once(run_id: str) -> dict[str, Any]:
    """Claim, run, and persist one analysis without exposing source text in logs."""
    repository = medical_analysis_repository
    run = repository.get_worker_run(run_id)
    if not run:
        log.info("Medical insight run %s no longer exists", run_id)
        return {"run_id": run_id, "status": "not_found"}

    if run["status"] in {SUCCEEDED, FAILED}:
        return run

    # Claiming the row is separate from loading it. A duplicate Celery
    # delivery that sees RUNNING must leave the first worker alone.
    claimed = repository.mark_running(run_id)
    if not claimed:
        current = repository.get_worker_run(run_id)
        return current or {"run_id": run_id, "status": "not_found"}

    attempt_count = claimed.get("attempt_count")
    owner_id = claimed.get("user_id") or claimed.get("requested_by") or "local-dev"
    try:
        if not repository.heartbeat(run_id, attempt_count=attempt_count):
            raise MedicalInsightError(
                "This analysis attempt is no longer active.",
                code="analysis_stale",
            )

        source = repository.get_source(
            claimed["document_id"],
            owner_id,
            claimed["workspace_id"],
        )
        if not source:
            raise MedicalInsightError(
                "The document was deleted before analysis started.",
                code="document_deleted",
            )
        if (
            source.get("source_hash") != claimed.get("source_hash")
            or source.get("parsed_source_hash") != claimed.get("parsed_source_hash")
        ):
            raise MedicalInsightError(
                "The parsed document changed before analysis started.",
                code="source_changed",
            )

        provider = get_provider(
            claimed["provider"],
            claimed["model_name"],
            timeout_seconds=int(
                claimed.get("timeout_seconds") or settings.MEDICAL_AI_TIMEOUT_SECONDS
            ),
            max_output_tokens=int(
                claimed.get("max_output_tokens") or settings.MEDICAL_AI_MAX_OUTPUT_TOKENS
            ),
            retry_count=int(
                claimed.get("provider_retry_count")
                if claimed.get("provider_retry_count") is not None
                else settings.MEDICAL_AI_PROVIDER_RETRY_COUNT
            ),
        )
        analyzer = MedicalInsightAnalyzer(
            provider=provider,
            max_input_tokens=int(
                claimed.get("max_input_tokens")
                or settings.MEDICAL_AI_MAX_INPUT_TOKENS
            ),
            timeout_seconds=int(
                claimed.get("timeout_seconds") or settings.MEDICAL_AI_TIMEOUT_SECONDS
            ),
            redact_pii=bool(
                claimed.get("redact_pii", settings.MEDICAL_AI_REDACT_PII)
            ),
            schema_version=claimed["schema_version"],
            prompt_version=claimed["prompt_version"],
        )
        output = analyzer.run(
            source["chunks"],
            sections=source["sections"],
            source_warnings=source.get("source_warnings"),
            title=source["title"],
            document_kind=source["document_kind"],
            language=source["language"],
        )
        if not repository.heartbeat(run_id, attempt_count=attempt_count):
            raise MedicalInsightError(
                "This analysis attempt is no longer active.",
                code="analysis_stale",
            )
        return repository.save_success(
            run_id,
            output,
            attempt_count=attempt_count,
        )
    except MedicalInsightError as exc:
        repository.save_failure(
            run_id,
            exc.code,
            str(exc),
            attempt_count=attempt_count,
        )
        log.warning("Medical insight run %s failed: %s", run_id, exc.code)
        return {
            "run_id": run_id,
            "status": "failed",
            "error_code": exc.code,
            "error_message": str(exc),
        }
    except Exception:
        # Keep the traceback for server diagnostics, but never include the
        # prompt, source chunks, or provider response in the log message.
        log.exception("Medical insight run %s failed unexpectedly", run_id)
        repository.save_failure(
            run_id,
            "analysis_failed",
            "Medical insight analysis failed.",
            attempt_count=attempt_count,
        )
        return {
            "run_id": run_id,
            "status": "failed",
            "error_code": "analysis_failed",
            "error_message": "Medical insight analysis failed.",
        }


@celery_app.task(bind=True, name="app.tasks.medical_analysis.run_medical_insight")
def run_medical_insight(self, run_id: str) -> dict[str, Any]:
    """Celery entrypoint; the same helper is used by local background tasks."""
    return run_medical_analysis_once(run_id)
