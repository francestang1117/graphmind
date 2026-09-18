"""API contract tests for the disease profile boundary."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from app.api.endpoints import disease_profiles
from app.core.errors import AppError
from app.services.medical.disease_profile.exceptions import DiseaseProfileError


def _link() -> dict:
    return {
        "id": "link-1",
        "document_id": "document-1",
        "concept_id": "mesh:D000795",
        "preferred_name_en": "Fabry Disease",
        "preferred_name_zh": "法布雷病",
        "matched_alias": "法布雷病",
        "ontology_version": "test-v1",
        "link_source": "manual_selection",
        "source_search_run_id": None,
        "created_at": "2026-09-18T00:00:00+00:00",
        "updated_at": "2026-09-18T00:00:00+00:00",
    }


def _summary(concept_id: str = "mesh:D000795") -> dict:
    return {
        "concept_id": concept_id,
        "preferred_name_en": "Fabry Disease",
        "preferred_name_zh": "法布雷病",
        "ontology_version": "test-v1",
        "document_count": 1,
        "analysis_count": 1,
        "external_article_count": 0,
        "saved_question_count": 0,
        "last_updated_at": "2026-09-18T00:00:00+00:00",
        "section_counts": {},
        "warnings": [],
    }


def _patch_scope(monkeypatch) -> None:
    monkeypatch.setattr(
        disease_profiles,
        "_scope",
        lambda _user, workspace_id: workspace_id,
    )
    monkeypatch.setattr(disease_profiles, "_require_storage", lambda: None)


def test_create_link_api_passes_scope_and_returns_idempotent_status(monkeypatch):
    _patch_scope(monkeypatch)
    captured = {}

    def create_link(**kwargs):
        captured.update(kwargs)
        return _link(), True

    monkeypatch.setattr(disease_profiles.disease_profile_service, "create_link", create_link)
    body = disease_profiles.DiseaseLinkCreateRequest(
        concept_id="mesh:D000795",
        matched_alias="法布雷病",
    )

    response = asyncio.run(
        disease_profiles.create_disease_link(
            "document-1",
            body,
            workspace_id="workspace-1",
            user=SimpleNamespace(id="user-1"),
        )
    )

    assert response.created is True
    assert response.link.concept_id == "mesh:D000795"
    assert captured == {
        "user_id": "user-1",
        "workspace_id": "workspace-1",
        "document_id": "document-1",
        "concept_id": "mesh:D000795",
        "matched_alias": "法布雷病",
        "source_search_run_id": None,
    }


def test_create_link_api_maps_second_primary_disease_to_conflict(monkeypatch):
    _patch_scope(monkeypatch)

    def create_link(**_kwargs):
        raise DiseaseProfileError(
            "This document already has a primary disease.",
            code="disease_link_primary_exists",
            status_code=409,
        )

    monkeypatch.setattr(disease_profiles.disease_profile_service, "create_link", create_link)
    body = disease_profiles.DiseaseLinkCreateRequest(
        concept_id="mesh:D005776",
        matched_alias="戈谢病",
    )

    with pytest.raises(AppError) as error:
        asyncio.run(
            disease_profiles.create_disease_link(
                "document-1",
                body,
                workspace_id="workspace-1",
                user=SimpleNamespace(id="user-1"),
            )
        )

    assert error.value.code == "disease_link_primary_exists"
    assert error.value.status_code == 409


def test_list_profiles_encodes_the_next_cursor(monkeypatch):
    _patch_scope(monkeypatch)
    captured = {}

    def list_profiles(**kwargs):
        captured.update(kwargs)
        return {"items": [_summary()], "next_cursor": "mesh:D005776"}

    monkeypatch.setattr(disease_profiles.disease_profile_service, "list_profiles", list_profiles)
    response = asyncio.run(
        disease_profiles.list_disease_profiles(
            workspace_id="workspace-1",
            limit=20,
            cursor=None,
            user=SimpleNamespace(id="user-1"),
        )
    )

    assert response.items[0].concept_id == "mesh:D000795"
    assert disease_profiles._decode_cursor(response.next_cursor or "", kind="concept") == "mesh:D005776"
    assert captured == {
        "user_id": "user-1",
        "workspace_id": "workspace-1",
        "limit": 20,
        "cursor_concept_id": None,
    }


def test_profile_items_rejects_malformed_cursor_before_service_call(monkeypatch):
    _patch_scope(monkeypatch)
    service_called = False

    def get_items(**_kwargs):
        nonlocal service_called
        service_called = True
        return None

    monkeypatch.setattr(disease_profiles.disease_profile_service, "get_items", get_items)
    malformed = "not-a-valid-base64-cursor"

    with pytest.raises(AppError) as error:
        asyncio.run(
            disease_profiles.get_disease_profile_items(
                "mesh:D000795",
                workspace_id="workspace-1",
                section="key_findings",
                limit=20,
                cursor=malformed,
                user=SimpleNamespace(id="user-1"),
            )
        )

    assert error.value.code == "disease_profile_invalid_cursor"
    assert error.value.status_code == 422
    assert service_called is False


def test_profile_items_rejects_unbounded_offset_cursor_before_service_call(monkeypatch):
    _patch_scope(monkeypatch)
    service_called = False

    def get_items(**_kwargs):
        nonlocal service_called
        service_called = True
        return None

    monkeypatch.setattr(disease_profiles.disease_profile_service, "get_items", get_items)
    oversized = disease_profiles._encode_cursor("10001")

    with pytest.raises(AppError) as error:
        asyncio.run(
            disease_profiles.get_disease_profile_items(
                "mesh:D000795",
                workspace_id="workspace-1",
                section="key_findings",
                limit=20,
                cursor=oversized,
                user=SimpleNamespace(id="user-1"),
            )
        )

    assert error.value.code == "disease_profile_invalid_cursor"
    assert error.value.status_code == 422
    assert service_called is False


def test_delete_link_returns_no_content_and_forwards_scope(monkeypatch):
    _patch_scope(monkeypatch)
    captured = {}

    def delete_link(**kwargs):
        captured.update(kwargs)
        return True

    monkeypatch.setattr(disease_profiles.disease_profile_service, "delete_link", delete_link)
    response = asyncio.run(
        disease_profiles.delete_disease_link(
            "document-1",
            "mesh:D000795",
            workspace_id="workspace-1",
            user=SimpleNamespace(id="user-1"),
        )
    )

    assert response.status_code == 204
    assert captured == {
        "user_id": "user-1",
        "workspace_id": "workspace-1",
        "document_id": "document-1",
        "concept_id": "mesh:D000795",
    }
