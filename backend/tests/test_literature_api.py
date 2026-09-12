"""API boundary tests for confirmation and workspace scoping."""

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import BackgroundTasks, HTTPException

from app.api.endpoints import literature
from app.core.errors import AppError
from app.services.medical.terminology.models import ConceptSelection


def _body(**overrides) -> literature.LiteratureSearchRequest:
    values = {
        "question": "What is known about Fabry disease?",
        "external_search_confirmed": False,
    }
    values.update(overrides)
    return literature.LiteratureSearchRequest(**values)


def _document(monkeypatch, *, workspace_id="workspace-a") -> None:
    monkeypatch.setattr(
        literature,
        "resolve_workspace_id",
        lambda *_args: workspace_id,
    )
    monkeypatch.setattr(
        literature.document_service,
        "get_document_by_id",
        lambda document_id, user_id, workspace_id=None: {
            "document_id": document_id,
            "user_id": user_id,
            "workspace_id": workspace_id,
            "original_filename": "paper.pdf",
        },
    )


def test_preview_returns_exact_query_and_disclosure(monkeypatch) -> None:
    _document(monkeypatch)
    result = asyncio.run(
        literature.preview_literature_search(
            "document-a",
            _body(),
            workspace_id="workspace-a",
            user=SimpleNamespace(id="user-a"),
        )
    )

    assert result["document_id"] == "document-a"
    assert result["workspace_id"] == "workspace-a"
    assert result["detected_concepts"][0]["normalized"] == "Fabry disease"
    assert result["external_data"]["sends_document_content"] is False
    assert len(result["query_fingerprint"]) == 64
    assert result["resolution_status"] == "ready"
    assert result["ontology_version"]


def test_preview_returns_ambiguous_disease_without_external_query(monkeypatch) -> None:
    _document(monkeypatch)
    result = asyncio.run(
        literature.preview_literature_search(
            "document-a",
            _body(question="What is known about ALS?"),
            workspace_id="workspace-a",
            user=SimpleNamespace(id="user-a"),
        )
    )

    assert result["resolution_status"] == "needs_confirmation"
    assert result["ambiguous_concepts"]
    assert result["pubmed_query"] is None
    assert result["query_fingerprint"] is None
    assert result["ambiguous_concepts"][0]["candidates"]


def test_start_requires_confirmation_before_queueing(monkeypatch) -> None:
    _document(monkeypatch)
    queued = []
    monkeypatch.setattr(literature, "_enqueue", lambda run_id, tasks: queued.append(run_id))

    with pytest.raises(AppError) as exc:
        asyncio.run(
            literature.start_literature_search(
                "document-a",
                _body(),
                BackgroundTasks(),
                workspace_id="workspace-a",
                user=SimpleNamespace(id="user-a"),
            )
        )

    assert exc.value.status_code == 409
    assert exc.value.code == "external_search_confirmation_required"
    assert queued == []


def test_start_rejects_stale_query_confirmation(monkeypatch) -> None:
    _document(monkeypatch)
    query = literature._build_query(_body())

    with pytest.raises(AppError) as exc:
        asyncio.run(
            literature.start_literature_search(
                "document-a",
                _body(
                    external_search_confirmed=True,
                    query_fingerprint="0" * 64,
                ),
                BackgroundTasks(),
                workspace_id="workspace-a",
                user=SimpleNamespace(id="user-a"),
            )
        )

    assert query.query_hash != "0" * 64
    assert exc.value.status_code == 409
    assert exc.value.code == "external_search_query_changed"


def test_start_rejects_unresolved_concept_before_creating_run(monkeypatch) -> None:
    _document(monkeypatch)
    queued = []
    monkeypatch.setattr(literature, "_enqueue", lambda run_id, tasks: queued.append(run_id))

    with pytest.raises(AppError) as exc:
        asyncio.run(
            literature.start_literature_search(
                "document-a",
                _body(
                    question="What is known about ALS?",
                    external_search_confirmed=True,
                    query_fingerprint="0" * 64,
                ),
                BackgroundTasks(),
                workspace_id="workspace-a",
                user=SimpleNamespace(id="user-a"),
            )
        )

    assert exc.value.status_code == 409
    assert exc.value.code == "literature_concept_confirmation_required"
    assert queued == []


def test_start_queues_confirmed_query_inside_scope(monkeypatch) -> None:
    _document(monkeypatch)
    query = literature._build_query(_body())
    captured = {}

    class FakeRepository:
        def create_or_reuse(self, **kwargs):
            captured.update(kwargs)
            return {"run_id": "run-1", "status": "queued", "articles": []}, True

    monkeypatch.setattr(literature, "literature_repository", FakeRepository())
    monkeypatch.setattr(literature, "_enqueue", lambda run_id, tasks: captured.update(enqueued=run_id))

    response = asyncio.run(
        literature.start_literature_search(
            "document-a",
            _body(
                external_search_confirmed=True,
                query_fingerprint=query.query_hash,
            ),
            BackgroundTasks(),
            workspace_id="workspace-a",
            user=SimpleNamespace(id="user-a"),
        )
    )

    assert response.status_code == 202
    assert captured["user_id"] == "user-a"
    assert captured["workspace_id"] == "workspace-a"
    assert captured["document_id"] == "document-a"
    assert captured["enqueued"] == "run-1"


def test_start_accepts_a_valid_ambiguous_concept_selection(monkeypatch) -> None:
    _document(monkeypatch)
    preview = literature._build_query(_body(question="What is known about ALS?"))
    match = preview.ambiguous_concepts[0]
    selected = match.candidates[0].concept_id
    selected_query = literature._build_query(
        _body(
            question="What is known about ALS?",
            concept_selections=[
                ConceptSelection(match_id=match.match_id, concept_id=selected)
            ],
        )
    )
    captured = {}

    class FakeRepository:
        def create_or_reuse(self, **kwargs):
            captured.update(kwargs)
            return {"run_id": "run-als", "status": "queued", "articles": []}, True

    monkeypatch.setattr(literature, "literature_repository", FakeRepository())
    monkeypatch.setattr(literature, "_enqueue", lambda run_id, tasks: captured.update(enqueued=run_id))

    response = asyncio.run(
        literature.start_literature_search(
            "document-a",
            _body(
                question="What is known about ALS?",
                concept_selections=[
                    ConceptSelection(match_id=match.match_id, concept_id=selected)
                ],
                external_search_confirmed=True,
                query_fingerprint=selected_query.query_hash,
            ),
            BackgroundTasks(),
            workspace_id="workspace-a",
            user=SimpleNamespace(id="user-a"),
        )
    )

    assert response.status_code == 202
    assert captured["query"].resolution_status == "ready"
    assert captured["query"].selected_concept_ids == [selected]
    assert captured["enqueued"] == "run-als"


def test_preview_does_not_use_storage_fallback_for_other_workspace(monkeypatch) -> None:
    monkeypatch.setattr(literature, "resolve_workspace_id", lambda *_args: "workspace-b")
    monkeypatch.setattr(
        literature.document_service,
        "get_document_by_id",
        lambda *_args, **_kwargs: None,
    )

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            literature.preview_literature_search(
                "document-a",
                _body(),
                workspace_id="workspace-b",
                user=SimpleNamespace(id="user-a"),
            )
        )
    assert exc.value.status_code == 404
