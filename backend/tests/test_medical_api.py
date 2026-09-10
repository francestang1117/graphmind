"""Small route tests for the medical analysis endpoint."""

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import BackgroundTasks, HTTPException

from app.api.endpoints import documents, medical_insights
from app.core.errors import AppError
from app.services.medical.ai.analysis_repository import external_processing_fingerprint


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


def test_medical_analysis_does_not_fall_back_across_workspaces(monkeypatch):
    lookups = []

    monkeypatch.setattr(documents, "resolve_workspace_id", lambda *_: "workspace-b")
    monkeypatch.setattr(documents, "db_enabled", lambda: True)
    monkeypatch.setattr(
        documents.document_service,
        "get_document_by_id",
        lambda *_args, **_kwargs: None,
    )

    def scoped_lookup(*_args, **kwargs):
        lookups.append(kwargs)
        # This is what the storage-backed service would otherwise return for a
        # same-user document that belongs to workspace-a.
        if kwargs.get("allow_storage_fallback") is False:
            return None
        return {
            "document_id": "document-a",
            "filename": "paper.pdf",
            "file_path": "/tmp/paper.pdf",
            "original_filename": "paper.pdf",
        }

    monkeypatch.setattr(documents.document_service, "get_document", scoped_lookup)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            documents.get_medical_analysis(
                "paper.pdf",
                workspace_id="workspace-b",
                user=SimpleNamespace(id="user-a"),
            )
        )

    assert exc.value.status_code == 404
    assert lookups == [{"workspace_id": "workspace-b", "allow_storage_fallback": False}]


def test_external_medical_analysis_requires_explicit_confirmation(monkeypatch):
    monkeypatch.setattr(medical_insights.settings, "MEDICAL_AI_ENABLED", True)
    monkeypatch.setattr(medical_insights.settings, "MEDICAL_AI_PROVIDER", "openai")
    monkeypatch.setattr(medical_insights.settings, "MEDICAL_AI_MODEL", "test-model")
    monkeypatch.setattr(
        medical_insights,
        "resolve_workspace_id",
        lambda *_args: "workspace-a",
    )
    monkeypatch.setattr(
        medical_insights,
        "_get_scoped_document",
        lambda *_args: {"document_id": "document-a", "file_hash": "a" * 64},
    )
    monkeypatch.setattr(medical_insights, "_require_repository", lambda: None)
    monkeypatch.setattr(
        medical_insights.medical_analysis_repository,
        "get_source",
        lambda *_args: {
            "source_hash": "a" * 64,
            "parsed_source_hash": "b" * 64,
            "document_kind": "research_paper",
            "chunks": [{"id": "chunk-1", "text": "Result"}],
        },
    )
    monkeypatch.setattr(
        medical_insights,
        "get_provider",
        lambda *_args: SimpleNamespace(model_name="test-model"),
    )

    with pytest.raises(AppError) as exc:
        asyncio.run(
            medical_insights._start_analysis(
                "document-a",
                BackgroundTasks(),
                SimpleNamespace(id="user-a"),
                workspace_id="workspace-a",
                external_processing_confirmed=False,
                external_processing_config_fingerprint=None,
                force=False,
            )
        )

    assert exc.value.status_code == 409
    assert exc.value.code == "external_processing_confirmation_required"
    assert exc.value.details["provider"] == "openai"


def test_medical_insight_config_discloses_external_processing(monkeypatch):
    monkeypatch.setattr(medical_insights.settings, "MEDICAL_AI_ENABLED", True)
    monkeypatch.setattr(medical_insights.settings, "MEDICAL_AI_PROVIDER", "openai")
    monkeypatch.setattr(medical_insights.settings, "MEDICAL_AI_MODEL", "test-model")
    monkeypatch.setattr(medical_insights.settings, "MEDICAL_AI_REDACT_PII", True)
    monkeypatch.setattr(
        medical_insights,
        "get_provider",
        lambda *_args: SimpleNamespace(model_name="test-model"),
    )

    result = asyncio.run(
        medical_insights.get_medical_insight_config(SimpleNamespace(id="user-a"))
    )

    assert result == {
        "enabled": True,
        "configured": True,
        "provider": "openai",
        "model_name": "test-model",
        "external_processing": True,
        "requires_confirmation": True,
        "sends_selected_excerpts": True,
        "redact_pii": True,
        "config_fingerprint": external_processing_fingerprint(
            provider="openai",
            model_name="test-model",
            redact_pii=True,
        ),
    }


def test_external_confirmation_rejects_changed_redaction_config(monkeypatch):
    stale_fingerprint = external_processing_fingerprint(
        provider="openai",
        model_name="test-model",
        redact_pii=True,
    )
    monkeypatch.setattr(medical_insights.settings, "MEDICAL_AI_ENABLED", True)
    monkeypatch.setattr(medical_insights.settings, "MEDICAL_AI_PROVIDER", "openai")
    monkeypatch.setattr(medical_insights.settings, "MEDICAL_AI_MODEL", "test-model")
    monkeypatch.setattr(medical_insights.settings, "MEDICAL_AI_REDACT_PII", False)
    monkeypatch.setattr(
        medical_insights,
        "resolve_workspace_id",
        lambda *_args: "workspace-a",
    )
    monkeypatch.setattr(
        medical_insights,
        "_get_scoped_document",
        lambda *_args: {"document_id": "document-a", "file_hash": "a" * 64},
    )
    monkeypatch.setattr(medical_insights, "_require_repository", lambda: None)
    monkeypatch.setattr(
        medical_insights.medical_analysis_repository,
        "get_source",
        lambda *_args: {
            "source_hash": "a" * 64,
            "parsed_source_hash": "b" * 64,
            "document_kind": "research_paper",
            "chunks": [{"id": "chunk-1", "text": "Result"}],
        },
    )
    monkeypatch.setattr(
        medical_insights,
        "get_provider",
        lambda *_args: SimpleNamespace(model_name="test-model"),
    )

    with pytest.raises(AppError) as exc:
        asyncio.run(
            medical_insights._start_analysis(
                "document-a",
                BackgroundTasks(),
                SimpleNamespace(id="user-a"),
                workspace_id="workspace-a",
                external_processing_confirmed=True,
                external_processing_config_fingerprint=stale_fingerprint,
                force=False,
            )
        )

    assert exc.value.status_code == 409
    assert exc.value.code == "external_processing_config_changed"
    assert exc.value.details["redact_pii"] is False
    assert exc.value.details["config_fingerprint"] != stale_fingerprint
