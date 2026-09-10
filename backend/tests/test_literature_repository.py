"""Persistence tests for scoped, idempotent literature search runs."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.persistence import (
    DocumentRecord,
    LiteratureSearchResultRecord,
    LiteratureSearchRunRecord,
)
from app.services.medical.literature.exceptions import LiteratureError
from app.services.medical.literature.models import LiteratureArticle, LiteratureSearchPage
from app.services.medical.literature.query_builder import build_literature_query
from app.services.medical.literature.repository import LiteratureRepository


def _setup() -> tuple[sessionmaker, LiteratureRepository]:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(bind=engine)
    sessions = sessionmaker(bind=engine, autoflush=False, future=True)
    return sessions, LiteratureRepository(sessions, enabled=lambda: True)


def _document(document_id: str, user_id: str, workspace_id: str) -> DocumentRecord:
    return DocumentRecord(
        id=document_id,
        user_id=user_id,
        workspace_id=workspace_id,
        filename=f"{document_id}.pdf",
        stored_filename=f"{document_id}.pdf",
        original_filename="paper.pdf",
        file_extension=".pdf",
        file_type=".pdf",
        mime_type="application/pdf",
        file_hash="a" * 64,
        file_path=f"/tmp/{document_id}.pdf",
        file_size=10,
        status="indexed",
    )


def _page() -> LiteratureSearchPage:
    article = LiteratureArticle(
        external_id="12345678",
        title="Fabry disease and renal outcomes",
        abstract="A public abstract.",
        journal="Journal of Rare Diseases",
        publication_date="2024-01-02",
        publication_year=2024,
        authors=["Doe Jane"],
        publication_types=["Journal Article"],
        mesh_terms=["Fabry Disease"],
        language="eng",
        source_url="https://pubmed.ncbi.nlm.nih.gov/12345678/",
        metadata_hash="b" * 64,
        fetched_at=datetime.now(timezone.utc),
    )
    return LiteratureSearchPage(
        articles=[article],
        total_count=1,
        fetched_at=datetime.now(timezone.utc),
        warnings=["pubmed_email_not_configured"],
    )


def _query():
    return build_literature_query("What is known about Fabry disease?")


def test_search_run_is_idempotent_and_success_is_cached() -> None:
    sessions, repository = _setup()
    with sessions() as db:
        db.add(_document("document-a", "user-a", "workspace-a"))
        db.commit()

    first, created = repository.create_or_reuse(
        query=_query(),
        user_id="user-a",
        workspace_id="workspace-a",
        document_id="document-a",
        external_search_confirmed=True,
    )
    assert created is True
    saved = repository.save_success(first["run_id"], _page())
    assert saved["status"] == "succeeded"
    assert saved["result_count"] == 1
    assert saved["articles"][0]["external_id"] == "12345678"
    assert saved["warnings"] == ["pubmed_email_not_configured"]

    reused, was_created = repository.create_or_reuse(
        query=_query(),
        user_id="user-a",
        workspace_id="workspace-a",
        document_id="document-a",
        external_search_confirmed=True,
    )
    assert was_created is False
    assert reused["run_id"] == first["run_id"]
    assert len(reused["articles"]) == 1


def test_expired_queued_run_is_reused_and_requeued() -> None:
    sessions, repository = _setup()
    with sessions() as db:
        db.add(_document("document-a", "user-a", "workspace-a"))
        db.commit()
    first, _ = repository.create_or_reuse(
        query=_query(),
        user_id="user-a",
        workspace_id="workspace-a",
        document_id="document-a",
        external_search_confirmed=True,
    )
    with sessions() as db:
        row = db.get(LiteratureSearchRunRecord, first["run_id"])
        row.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()

    requeued, created = repository.create_or_reuse(
        query=_query(),
        user_id="user-a",
        workspace_id="workspace-a",
        document_id="document-a",
        external_search_confirmed=True,
    )
    assert created is True
    assert requeued["run_id"] == first["run_id"]
    assert requeued["status"] == "queued"


def test_runs_are_isolated_by_user_workspace_and_document() -> None:
    sessions, repository = _setup()
    with sessions() as db:
        db.add(_document("document-a", "user-a", "workspace-a"))
        db.add(_document("document-b", "user-a", "workspace-b"))
        db.commit()

    run_a, _ = repository.create_or_reuse(
        query=_query(),
        user_id="user-a",
        workspace_id="workspace-a",
        document_id="document-a",
        external_search_confirmed=True,
    )
    run_b, _ = repository.create_or_reuse(
        query=_query(),
        user_id="user-a",
        workspace_id="workspace-b",
        document_id="document-b",
        external_search_confirmed=True,
    )
    assert run_a["run_id"] != run_b["run_id"]

    with pytest.raises(LiteratureError, match="not found"):
        repository.create_or_reuse(
            query=_query(),
            user_id="user-b",
            workspace_id="workspace-a",
            document_id="document-a",
            external_search_confirmed=True,
        )


def test_delete_for_document_removes_runs_and_results_but_keeps_public_cache() -> None:
    sessions, repository = _setup()
    with sessions() as db:
        db.add(_document("document-a", "user-a", "workspace-a"))
        db.commit()
    run, _ = repository.create_or_reuse(
        query=_query(),
        user_id="user-a",
        workspace_id="workspace-a",
        document_id="document-a",
        external_search_confirmed=True,
    )
    repository.save_success(run["run_id"], _page())
    # The compatibility delete path may not know the workspace. It must still
    # clear runs for this document instead of assuming the user's default one.
    repository.delete_for_document("document-a", "user-a")

    assert repository.get_run(run["run_id"], "user-a", "workspace-a") is None
    with sessions() as db:
        assert db.scalar(select(LiteratureSearchRunRecord.id)) is None
        assert db.scalar(select(LiteratureSearchResultRecord.id)) is None
