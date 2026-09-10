"""Background task for one bounded PubMed search."""

from __future__ import annotations

import asyncio
from datetime import date
import logging
from typing import Any

from app.core.celery_app import celery_app
from app.services.medical.literature.exceptions import LiteratureError
from app.services.medical.literature.models import LiteratureQuery
from app.services.medical.literature.pubmed_provider import PubMedProvider
from app.services.medical.literature.repository import (
    FAILED,
    SUCCEEDED,
    literature_repository,
)

log = logging.getLogger(__name__)


def run_literature_search_once(run_id: str) -> dict[str, Any]:
    """Claim, fetch, and persist one search without logging the query text."""
    repository = literature_repository
    run = repository.get_worker_run(run_id)
    if not run:
        log.info("Literature search run %s no longer exists", run_id)
        return {"run_id": run_id, "status": "not_found"}
    if run["status"] in {SUCCEEDED, FAILED}:
        return run

    claimed = repository.mark_running(run_id)
    if not claimed:
        current = repository.get_worker_run(run_id)
        return current or {"run_id": run_id, "status": "not_found"}

    attempt_count = claimed.get("attempt_count")
    try:
        if not repository.heartbeat(run_id, attempt_count=attempt_count):
            raise LiteratureError(
                "This literature search attempt is no longer active.",
                code="literature_run_stale",
            )
        query = _query_from_run(claimed)
        page = asyncio.run(PubMedProvider().search(query))
        if not repository.heartbeat(run_id, attempt_count=attempt_count):
            raise LiteratureError(
                "This literature search attempt is no longer active.",
                code="literature_run_stale",
            )
        return repository.save_success(
            run_id,
            page,
            attempt_count=attempt_count,
        )
    except LiteratureError as exc:
        repository.save_failure(
            run_id,
            exc.code,
            str(exc),
            attempt_count=attempt_count,
        )
        log.warning("Literature search run %s failed: %s", run_id, exc.code)
        return {
            "run_id": run_id,
            "status": FAILED,
            "error_code": exc.code,
            "error_message": str(exc),
        }
    except Exception:
        log.exception("Literature search run %s failed unexpectedly", run_id)
        repository.save_failure(
            run_id,
            "literature_search_failed",
            "Literature search failed.",
            attempt_count=attempt_count,
        )
        return {
            "run_id": run_id,
            "status": FAILED,
            "error_code": "literature_search_failed",
            "error_message": "Literature search failed.",
        }


def _query_from_run(run: dict[str, Any]) -> LiteratureQuery:
    return LiteratureQuery(
        question=run.get("question") or "medical research question",
        sanitized_question=run.get("question") or "",
        normalized_query=run["normalized_query"],
        detected_concepts=[],
        date_from=_parse_date(run.get("date_from")),
        date_to=_parse_date(run.get("date_to")),
        study_types=list(run.get("study_types") or []),
        sort=run.get("sort") or "relevance",
        max_results=int(run.get("max_results") or 20),
        provider=run.get("provider") or "pubmed",
        query_hash=run["query_hash"],
    )


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


@celery_app.task(bind=True, name="app.tasks.literature_search.run_literature_search")
def run_literature_search(self, run_id: str) -> dict[str, Any]:
    """Celery entrypoint; local mode uses the same synchronous helper."""
    return run_literature_search_once(run_id)
