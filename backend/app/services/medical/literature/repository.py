"""Persistence and lifecycle rules for scoped literature searches."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import json
import logging
from typing import Any, Callable
import uuid

from app.core.config import settings
from app.core.database import SessionLocal, db_enabled
from app.models.persistence import (
    DocumentRecord,
    LiteratureArticleRecord,
    LiteratureSearchResultRecord,
    LiteratureSearchRunRecord,
)
from app.services.medical.literature.exceptions import LiteratureError
from app.services.medical.literature.models import LiteratureArticle, LiteratureQuery, LiteratureSearchPage

try:
    from sqlalchemy import delete, select
    from sqlalchemy.dialects.postgresql import insert as postgres_insert
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert
    from sqlalchemy.exc import IntegrityError, SQLAlchemyError
except ImportError:  # pragma: no cover - only before DB dependencies are installed
    delete = None
    select = None
    postgres_insert = None
    sqlite_insert = None
    IntegrityError = Exception
    SQLAlchemyError = Exception

log = logging.getLogger(__name__)

QUEUED = "queued"
RUNNING = "running"
SUCCEEDED = "succeeded"
FAILED = "failed"


class LiteratureRepository:
    """Store one search result set inside one user's workspace boundary."""

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
            and LiteratureArticleRecord
            and LiteratureSearchResultRecord
            and LiteratureSearchRunRecord
        )

    def create_or_reuse(
        self,
        *,
        query: LiteratureQuery,
        user_id: str,
        workspace_id: str,
        document_id: str,
        external_search_confirmed: bool = False,
        cache_ttl_seconds: int | None = None,
        queue_lease_seconds: int = 300,
    ) -> tuple[dict[str, Any], bool]:
        """Create one queued run or reuse a fresh/active run.

        The document row is locked before the search row. Deletion and search
        creation therefore serialize in the same order as other document
        workflows.
        """
        self._require_available()
        if not external_search_confirmed:
            raise LiteratureError(
                "Confirm the external literature search before starting it.",
                code="external_search_confirmation_required",
            )
        if not document_id:
            raise LiteratureError(
                "A source document is required for literature search.",
                code="literature_document_required",
            )

        now = _utc_now()
        cache_ttl = max(0, int(
            settings.PUBMED_CACHE_TTL_SECONDS
            if cache_ttl_seconds is None
            else cache_ttl_seconds
        ))
        query_hash = query.query_hash
        try:
            with self.session_factory() as db:
                document = self._document(
                    db,
                    document_id,
                    user_id,
                    workspace_id,
                    lock=True,
                )
                if not document:
                    raise LiteratureError(
                        "The source document was not found.",
                        code="literature_document_not_found",
                    )

                row = db.scalars(
                    select(LiteratureSearchRunRecord)
                    .where(
                        LiteratureSearchRunRecord.user_id == user_id,
                        LiteratureSearchRunRecord.workspace_id == workspace_id,
                        LiteratureSearchRunRecord.document_id == document.id,
                        LiteratureSearchRunRecord.query_hash == query_hash,
                        LiteratureSearchRunRecord.provider == query.provider,
                    )
                    .with_for_update()
                ).first()

                if row and row.status == SUCCEEDED and _cache_is_fresh(row, now, cache_ttl):
                    db.commit()
                    return _run_payload(db, row), False
                if row and row.status in {QUEUED, RUNNING} and not _lease_expired(row, now):
                    db.commit()
                    return _run_payload(db, row), False

                if row:
                    self._clear_results(db, row.id)
                    row.question = query.sanitized_question or query.question
                    row.normalized_query = query.normalized_query
                    row.date_from = query.date_from.isoformat() if query.date_from else None
                    row.date_to = query.date_to.isoformat() if query.date_to else None
                    row.study_types_json = _dump_json(query.study_types)
                    row.sort = query.sort
                    row.max_results = query.max_results
                    row.status = QUEUED
                    row.result_count = 0
                    row.error_code = ""
                    row.error_message = ""
                    row.warnings_json = "[]"
                    # Keep this counter monotonic. The random token below is
                    # the primary fence, while the counter helps operators
                    # see how many times a lease was reclaimed.
                    row.attempt_count = max(0, int(row.attempt_count or 0))
                    row.attempt_token = None
                    row.external_search_confirmed_at = now
                    row.last_heartbeat_at = None
                    row.lease_expires_at = now + timedelta(seconds=max(1, queue_lease_seconds))
                    row.started_at = None
                    row.completed_at = None
                    row.fetched_at = None
                    row.created_at = now
                    row.updated_at = now
                    created = True
                else:
                    row = LiteratureSearchRunRecord(
                        id=uuid.uuid4().hex,
                        user_id=user_id,
                        workspace_id=workspace_id,
                        document_id=document.id,
                        question=query.sanitized_question or query.question,
                        normalized_query=query.normalized_query,
                        query_hash=query_hash,
                        provider=query.provider,
                        status=QUEUED,
                        date_from=query.date_from.isoformat() if query.date_from else None,
                        date_to=query.date_to.isoformat() if query.date_to else None,
                        study_types_json=_dump_json(query.study_types),
                        sort=query.sort,
                        max_results=query.max_results,
                        result_count=0,
                        error_code="",
                        error_message="",
                        warnings_json="[]",
                        attempt_count=0,
                        external_search_confirmed_at=now,
                        last_heartbeat_at=None,
                        lease_expires_at=now + timedelta(seconds=max(1, queue_lease_seconds)),
                        started_at=None,
                        completed_at=None,
                        fetched_at=None,
                        created_at=now,
                        updated_at=now,
                    )
                    db.add(row)
                    created = True
                db.commit()
                return _run_payload(db, row), created
        except LiteratureError:
            raise
        except IntegrityError:
            # The unique key is the final guard for two requests that arrive
            # together before either one can observe the other row.
            with self.session_factory() as db:
                row = db.scalars(
                    select(LiteratureSearchRunRecord).where(
                        LiteratureSearchRunRecord.user_id == user_id,
                        LiteratureSearchRunRecord.workspace_id == workspace_id,
                        LiteratureSearchRunRecord.document_id == document_id,
                        LiteratureSearchRunRecord.query_hash == query_hash,
                        LiteratureSearchRunRecord.provider == query.provider,
                    )
                ).first()
                if row:
                    return _run_payload(db, row), False
            raise LiteratureError(
                "Could not create the literature search.",
                code="literature_storage_failed",
            )
        except (SQLAlchemyError, OSError, RuntimeError) as exc:
            log.warning("Could not create literature search: %s", exc)
            raise LiteratureError(
                "Could not create the literature search.",
                code="literature_storage_failed",
            ) from exc

    def mark_running(self, run_id: str) -> dict[str, Any] | None:
        """Claim a queued run and extend its worker lease."""
        self._require_available()
        now = _utc_now()
        with self.session_factory() as db:
            document, row = self._lock_run_context(db, run_id, require_document=True)
            if not document or not row or row.status != QUEUED:
                return None
            row.status = RUNNING
            row.attempt_count = (row.attempt_count or 0) + 1
            row.attempt_token = uuid.uuid4().hex
            row.started_at = row.started_at or now
            row.last_heartbeat_at = now
            row.lease_expires_at = now + timedelta(seconds=_running_lease_seconds())
            row.updated_at = now
            db.commit()
            return _run_dict(row, include_attempt_token=True)

    def heartbeat(
        self,
        run_id: str,
        *,
        attempt_count: int | None = None,
        attempt_token: str | None = None,
    ) -> bool:
        """Keep a worker lease alive only while the source document is live."""
        self._require_available()
        now = _utc_now()
        with self.session_factory() as db:
            document, row = self._lock_run_context(db, run_id, require_document=True)
            if not document or not row or row.status != RUNNING:
                return False
            if not _attempt_matches(row, attempt_count, attempt_token):
                return False
            row.last_heartbeat_at = now
            row.lease_expires_at = now + timedelta(seconds=_running_lease_seconds())
            row.updated_at = now
            db.commit()
            return True

    def get_worker_run(self, run_id: str) -> dict[str, Any] | None:
        """Read worker metadata without exposing it through a public route."""
        self._require_available()
        with self.session_factory() as db:
            row = db.scalars(
                select(LiteratureSearchRunRecord).where(
                    LiteratureSearchRunRecord.id == run_id
                )
            ).first()
            return _run_dict(row, include_attempt_token=True) if row else None

    def save_success(
        self,
        run_id: str,
        page: LiteratureSearchPage,
        *,
        attempt_count: int | None = None,
        attempt_token: str | None = None,
    ) -> dict[str, Any]:
        """Replace one run's ranked results and mark it successful atomically."""
        self._require_available()
        now = _utc_now()
        try:
            with self.session_factory() as db:
                document, row = self._lock_run_context(db, run_id, require_document=True)
                if not row:
                    raise LiteratureError(
                        "The literature search run was not found.",
                        code="literature_run_not_found",
                    )
                if not document:
                    raise LiteratureError(
                        "The source document was deleted before search finished.",
                        code="literature_document_deleted",
                    )
                if row.status == SUCCEEDED:
                    return _run_payload(db, row)
                if row.status not in {QUEUED, RUNNING}:
                    raise LiteratureError(
                        "The literature search run is no longer active.",
                        code="literature_run_not_active",
                    )
                if row.status == RUNNING:
                    if not _attempt_matches(row, attempt_count, attempt_token):
                        raise LiteratureError(
                            "The literature search attempt is no longer active.",
                            code="literature_run_stale",
                        )
                elif (
                    attempt_count is not None and row.attempt_count != attempt_count
                ) or (attempt_token is not None and row.attempt_token != attempt_token):
                    raise LiteratureError(
                        "The literature search attempt is no longer active.",
                        code="literature_run_stale",
                    )
                if row.status == RUNNING and _lease_expired(row, now):
                    raise LiteratureError(
                        "The literature search lease expired.",
                        code="literature_run_stalled",
                    )

                self._clear_results(db, row.id)
                for rank, article in enumerate(page.articles, start=1):
                    article_row = _upsert_article(db, article, now)
                    db.add(
                        LiteratureSearchResultRecord(
                            id=uuid.uuid4().hex,
                            search_run_id=row.id,
                            article_id=article_row.id,
                            provider_rank=rank,
                            matched_terms_json="[]",
                            selected_for_analysis=False,
                            created_at=now,
                        )
                    )

                row.status = SUCCEEDED
                row.result_count = len(page.articles)
                row.error_code = ""
                row.error_message = ""
                row.warnings_json = _dump_json(page.warnings)
                row.completed_at = now
                row.fetched_at = page.fetched_at
                row.last_heartbeat_at = now
                row.lease_expires_at = None
                row.attempt_token = None
                row.updated_at = now
                db.commit()
                return _run_payload(db, row)
        except LiteratureError:
            raise
        except (SQLAlchemyError, OSError, RuntimeError) as exc:
            log.exception("Could not save literature search %s", run_id)
            raise LiteratureError(
                "Could not save the literature search results.",
                code="literature_storage_failed",
            ) from exc

    def save_failure(
        self,
        run_id: str,
        code: str,
        message: str,
        *,
        attempt_count: int | None = None,
        attempt_token: str | None = None,
    ) -> None:
        """Record a bounded, public-safe failure state."""
        if not self.available():
            return
        now = _utc_now()
        try:
            with self.session_factory() as db:
                _document, row = self._lock_run_context(
                    db, run_id, require_document=False
                )
                if not row or row.status == SUCCEEDED:
                    return
                if row.status == RUNNING and not _attempt_matches(
                    row, attempt_count, attempt_token
                ):
                    return
                if row.status != RUNNING and (
                    (attempt_count is not None and row.attempt_count != attempt_count)
                    or (attempt_token is not None and row.attempt_token != attempt_token)
                ):
                    return
                row.status = FAILED
                row.error_code = str(code or "literature_search_failed")[:80]
                row.error_message = str(message or "Literature search failed.")[:1000]
                row.completed_at = now
                row.last_heartbeat_at = now
                row.lease_expires_at = None
                row.attempt_token = None
                row.updated_at = now
                db.commit()
        except (SQLAlchemyError, OSError, RuntimeError):
            log.exception("Could not record literature search failure %s", run_id)

    def get_run(
        self,
        run_id: str,
        user_id: str,
        workspace_id: str,
    ) -> dict[str, Any] | None:
        """Return a run only when its document and workspace are both live."""
        self._require_available()
        now = _utc_now()
        with self.session_factory() as db:
            row = db.scalars(
                select(LiteratureSearchRunRecord).where(
                    LiteratureSearchRunRecord.id == run_id,
                    LiteratureSearchRunRecord.user_id == user_id,
                    LiteratureSearchRunRecord.workspace_id == workspace_id,
                )
            ).first()
            if not row:
                return None
            if row.document_id and not self._document(
                db, row.document_id, user_id, workspace_id
            ):
                return None
            if row.status in {QUEUED, RUNNING} and _lease_expired(row, now):
                row.status = FAILED
                row.error_code = "literature_search_stalled"
                row.error_message = "The literature search worker did not finish."
                row.completed_at = now
                row.lease_expires_at = None
                row.attempt_token = None
                row.updated_at = now
                db.commit()
            return _run_payload(db, row)

    def delete_for_document(
        self,
        document_id: str,
        user_id: str,
        workspace_id: str | None = None,
    ) -> None:
        """Remove search runs/results while retaining the public article cache."""
        if not self.available() or not document_id:
            return
        with self.session_factory() as db:
            filters = [
                LiteratureSearchRunRecord.document_id == document_id,
                LiteratureSearchRunRecord.user_id == user_id,
            ]
            if workspace_id is not None:
                filters.append(LiteratureSearchRunRecord.workspace_id == workspace_id)
            run_ids = list(
                db.scalars(
                    select(LiteratureSearchRunRecord.id).where(*filters)
                ).all()
            )
            if run_ids:
                db.execute(
                    delete(LiteratureSearchResultRecord).where(
                        LiteratureSearchResultRecord.search_run_id.in_(run_ids)
                    )
                )
                db.execute(
                    delete(LiteratureSearchRunRecord).where(
                        LiteratureSearchRunRecord.id.in_(run_ids)
                    )
                )
            db.commit()

    def _lock_run_context(self, db, run_id: str, *, require_document: bool):
        """Lock document first, then run, to keep all lifecycle paths ordered."""
        owner = db.execute(
            select(
                LiteratureSearchRunRecord.document_id,
                LiteratureSearchRunRecord.user_id,
                LiteratureSearchRunRecord.workspace_id,
            ).where(LiteratureSearchRunRecord.id == run_id)
        ).first()
        if not owner:
            return None, None
        document = None
        if owner.document_id:
            document = self._document(
                db,
                owner.document_id,
                owner.user_id,
                owner.workspace_id,
                lock=True,
            )
            if require_document and not document:
                return None, None
        row = db.scalars(
            select(LiteratureSearchRunRecord)
            .where(
                LiteratureSearchRunRecord.id == run_id,
                LiteratureSearchRunRecord.user_id == owner.user_id,
                LiteratureSearchRunRecord.workspace_id == owner.workspace_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        ).first()
        return document, row

    @staticmethod
    def _document(
        db,
        document_id: str,
        user_id: str,
        workspace_id: str,
        *,
        lock: bool = False,
    ):
        query = select(DocumentRecord).where(
            DocumentRecord.id == document_id,
            DocumentRecord.user_id == user_id,
            DocumentRecord.workspace_id == workspace_id,
            DocumentRecord.deleted_at.is_(None),
        )
        if lock:
            query = query.with_for_update()
        return db.scalars(query).first()

    @staticmethod
    def _clear_results(db, run_id: str) -> None:
        db.execute(
            delete(LiteratureSearchResultRecord).where(
                LiteratureSearchResultRecord.search_run_id == run_id
            )
        )

    def _require_available(self) -> None:
        if not self.available():
            raise LiteratureError(
                "Literature search persistence is unavailable.",
                code="literature_storage_unavailable",
            )


def _attempt_matches(
    row: LiteratureSearchRunRecord,
    attempt_count: int | None,
    attempt_token: str | None,
) -> bool:
    """Require the random fence for every active worker operation."""
    if not attempt_token or not row.attempt_token or row.attempt_token != attempt_token:
        return False
    return attempt_count is None or row.attempt_count == attempt_count


def _article_values(article: LiteratureArticle, now: datetime) -> dict[str, Any]:
    return {
        "id": uuid.uuid4().hex,
        "source": article.source,
        "external_id": article.external_id,
        "doi": article.doi,
        "pmcid": article.pmcid,
        "title": article.title,
        "abstract": article.abstract or "",
        "journal": article.journal,
        "publication_date": article.publication_date or "",
        "publication_year": article.publication_year,
        "authors_json": _dump_json(article.authors),
        "publication_types_json": _dump_json(article.publication_types),
        "mesh_terms_json": _dump_json(article.mesh_terms),
        "language": article.language,
        "source_url": article.source_url,
        "retraction_status": article.retraction_status,
        "metadata_hash": article.metadata_hash,
        "fetched_at": article.fetched_at,
        "created_at": now,
        "updated_at": now,
    }


def _upsert_article(db, article: LiteratureArticle, now: datetime) -> LiteratureArticleRecord:
    """Upsert public metadata so concurrent runs share one cache row."""
    values = _article_values(article, now)
    dialect = db.get_bind().dialect.name
    insert_factory = (
        postgres_insert
        if dialect == "postgresql"
        else sqlite_insert
        if dialect == "sqlite"
        else None
    )
    if insert_factory is None:
        row = db.scalars(
            select(LiteratureArticleRecord)
            .where(
                LiteratureArticleRecord.source == article.source,
                LiteratureArticleRecord.external_id == article.external_id,
            )
            .with_for_update()
        ).first()
        if not row:
            row = LiteratureArticleRecord(
                id=values["id"],
                source=article.source,
                external_id=article.external_id,
                created_at=now,
            )
            db.add(row)
        _update_article(row, article, now)
        db.flush()
        return row

    statement = insert_factory(LiteratureArticleRecord).values(**values)
    update_values = {
        name: getattr(statement.excluded, name)
        for name in values
        if name not in {"id", "created_at", "source", "external_id"}
    }
    statement = statement.on_conflict_do_update(
        index_elements=["source", "external_id"],
        set_=update_values,
    )
    db.execute(statement)
    return db.scalars(
        select(LiteratureArticleRecord)
        .where(
            LiteratureArticleRecord.source == article.source,
            LiteratureArticleRecord.external_id == article.external_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    ).one()


def _update_article(row: LiteratureArticleRecord, article: LiteratureArticle, now: datetime) -> None:
    for name, value in _article_values(article, now).items():
        if name not in {"id", "source", "external_id", "created_at"}:
            setattr(row, name, value)


def _run_payload(db, row: LiteratureSearchRunRecord) -> dict[str, Any]:
    payload = _run_dict(row)
    joined = db.execute(
        select(LiteratureSearchResultRecord, LiteratureArticleRecord)
        .join(
            LiteratureArticleRecord,
            LiteratureArticleRecord.id == LiteratureSearchResultRecord.article_id,
        )
        .where(LiteratureSearchResultRecord.search_run_id == row.id)
        .order_by(LiteratureSearchResultRecord.provider_rank.asc())
    ).all()
    payload["articles"] = [
        {
            **_article_dict(article),
            "provider_rank": result.provider_rank,
            "matched_terms": _loads_json(result.matched_terms_json, []),
            "selected_for_analysis": bool(result.selected_for_analysis),
        }
        for result, article in joined
    ]
    if row.status == SUCCEEDED and not payload["articles"]:
        payload["empty_reason"] = "no_results"
    return payload


def _run_dict(
    row: LiteratureSearchRunRecord | None,
    *,
    include_attempt_token: bool = False,
) -> dict[str, Any]:
    if not row:
        return {}
    payload = {
        "run_id": row.id,
        "user_id": row.user_id,
        "workspace_id": row.workspace_id,
        "document_id": row.document_id,
        "question": row.question,
        "normalized_query": row.normalized_query,
        "query_hash": row.query_hash,
        "provider": row.provider,
        "status": row.status,
        "date_from": row.date_from,
        "date_to": row.date_to,
        "study_types": _loads_json(row.study_types_json, []),
        "sort": row.sort,
        "max_results": row.max_results,
        "result_count": row.result_count,
        "warnings": _loads_json(row.warnings_json, []),
        "error_code": row.error_code or "",
        "error_message": row.error_message or "",
        "attempt_count": row.attempt_count,
        "started_at": _iso(row.started_at),
        "completed_at": _iso(row.completed_at),
        "fetched_at": _iso(row.fetched_at),
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }
    if include_attempt_token:
        payload["attempt_token"] = row.attempt_token
    return payload


def _article_dict(row: LiteratureArticleRecord) -> dict[str, Any]:
    return {
        "id": row.id,
        "source": row.source,
        "external_id": row.external_id,
        "doi": row.doi,
        "pmcid": row.pmcid,
        "title": row.title,
        "abstract": row.abstract or None,
        "journal": row.journal,
        "publication_date": row.publication_date or None,
        "publication_year": row.publication_year,
        "authors": _loads_json(row.authors_json, []),
        "publication_types": _loads_json(row.publication_types_json, []),
        "mesh_terms": _loads_json(row.mesh_terms_json, []),
        "language": row.language,
        "source_url": row.source_url,
        "retraction_status": row.retraction_status,
        "metadata_hash": row.metadata_hash,
        "fetched_at": _iso(row.fetched_at),
    }


def _cache_is_fresh(row: LiteratureSearchRunRecord, now: datetime, ttl: int) -> bool:
    if ttl <= 0 or not row.fetched_at:
        return False
    fetched_at = _aware(row.fetched_at)
    return now - fetched_at <= timedelta(seconds=ttl)


def _lease_expired(row: LiteratureSearchRunRecord, now: datetime) -> bool:
    return not row.lease_expires_at or _aware(row.lease_expires_at) <= now


def _running_lease_seconds() -> int:
    # Literature calls are short, but the lease is configurable through the
    # existing medical AI setting until a dedicated worker setting is needed.
    return max(60, int(getattr(settings, "MEDICAL_AI_RUNNING_LEASE_SECONDS", 900)))


def _dump_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _loads_json(value: str | None, default: Any) -> Any:
    try:
        parsed = json.loads(value or "")
    except (TypeError, json.JSONDecodeError):
        return default
    return parsed


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def _iso(value: datetime | date | None) -> str | None:
    return _aware(value).isoformat() if isinstance(value, datetime) else value.isoformat() if value else None


literature_repository = LiteratureRepository()
