"""Small route tests for the medical analysis endpoint."""

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.endpoints import documents


def test_medical_analysis_route_passes_user_and_workspace_scope(monkeypatch):
    requested = {}

    monkeypatch.setattr(
        documents,
        "resolve_workspace_id",
        lambda user_id, workspace_id: requested.update(
            {"user_id": user_id, "workspace_id": workspace_id}
        ) or "workspace-a",
    )
    monkeypatch.setattr(
        documents.document_service,
        "get_document_by_id",
        lambda identifier, user_id, workspace_id=None: {
            "document_id": identifier,
            "filename": "paper.pdf",
            "file_path": "/tmp/paper.pdf",
            "original_filename": "paper.pdf",
        },
    )
    monkeypatch.setattr(
        documents.medical_repository,
        "get_analysis",
        lambda identifier, user_id, workspace_id=None: {
            "document_id": identifier,
            "workspace_id": workspace_id,
            "document_kind": "research_paper",
            "sections": [],
        },
    )

    result = asyncio.run(
        documents.get_medical_analysis(
            "document-a",
            workspace_id="workspace-a",
            user=SimpleNamespace(id="user-a"),
        )
    )

    assert requested == {"user_id": "user-a", "workspace_id": "workspace-a"}
    assert result["document_id"] == "document-a"
    assert result["workspace_id"] == "workspace-a"


def test_medical_analysis_route_returns_404_for_missing_analysis(monkeypatch):
    monkeypatch.setattr(documents, "resolve_workspace_id", lambda *_: "workspace-a")
    monkeypatch.setattr(
        documents.document_service,
        "get_document_by_id",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        documents.document_service,
        "get_document",
        lambda *_args, **_kwargs: None,
    )

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            documents.get_medical_analysis(
                "missing", workspace_id="workspace-a", user=SimpleNamespace(id="user-a")
            )
        )

    assert exc.value.status_code == 404
