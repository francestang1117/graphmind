"""API contract tests for the disease profile boundary."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from app.api.endpoints import disease_profiles
from app.core.errors import AppError
from app.services.medical.disease_profile.exceptions import DiseaseProfileError
from app.services.medical.disease_profile.models import ComparisonPreviewRequest


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


def _comparison_preview_payload() -> dict:
    def document(document_id: str) -> dict:
        return {
            "document_id": document_id,
            "title": f"{document_id}.pdf",
            "open_filename": f"{document_id}.pdf",
            "analysis_run_id": f"run-{document_id}",
            "parsed_source_hash": f"parsed-{document_id}",
        }

    return {
        "concept_id": "mesh:D000795",
        "documents": [document("document-1"), document("document-2")],
        "discussion_questions": [],
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


def test_comparison_preview_api_forwards_scope_and_returns_strict_payload(monkeypatch):
    _patch_scope(monkeypatch)
    captured = {}

    def preview_comparison(**kwargs):
        captured.update(kwargs)
        return _comparison_preview_payload()

    monkeypatch.setattr(
        disease_profiles.disease_profile_service,
        "preview_comparison",
        preview_comparison,
    )
    body = ComparisonPreviewRequest(
        documents=[
            {
                "document_id": "document-1",
                "expected_parsed_source_hash": "parsed-document-1",
                "expected_analysis_run_id": "run-document-1",
            },
            {
                "document_id": "document-2",
                "expected_parsed_source_hash": "parsed-document-2",
                "expected_analysis_run_id": "run-document-2",
            },
        ],
        language="zh",
    )

    response = asyncio.run(
        disease_profiles.preview_disease_profile_comparison(
            "mesh:D000795",
            body,
            workspace_id="workspace-1",
            user=SimpleNamespace(id="user-1"),
        )
    )

    assert response.concept_id == "mesh:D000795"
    assert [item.document_id for item in response.documents] == [
        "document-1",
        "document-2",
    ]
    assert captured == {
        "user_id": "user-1",
        "workspace_id": "workspace-1",
        "concept_id": "mesh:D000795",
        "documents": [
            {
                "document_id": "document-1",
                "expected_parsed_source_hash": "parsed-document-1",
                "expected_analysis_run_id": "run-document-1",
            },
            {
                "document_id": "document-2",
                "expected_parsed_source_hash": "parsed-document-2",
                "expected_analysis_run_id": "run-document-2",
            },
        ],
        "language": "zh",
    }


@pytest.mark.parametrize(
    ("code", "status_code"),
    [
        ("comparison_invalid_selection", 422),
        ("comparison_source_not_found", 404),
        ("comparison_source_changed", 409),
        ("comparison_storage_unavailable", 503),
    ],
)
def test_comparison_preview_api_preserves_service_error_mapping(
    monkeypatch,
    code: str,
    status_code: int,
):
    _patch_scope(monkeypatch)

    def preview_comparison(**_kwargs):
        raise DiseaseProfileError(
            "comparison failed",
            code=code,
            status_code=status_code,
        )

    monkeypatch.setattr(
        disease_profiles.disease_profile_service,
        "preview_comparison",
        preview_comparison,
    )
    body = ComparisonPreviewRequest(
        documents=[_link_selection("document-1"), _link_selection("document-2")],
    )

    with pytest.raises(AppError) as error:
        asyncio.run(
            disease_profiles.preview_disease_profile_comparison(
                "mesh:D000795",
                body,
                workspace_id="workspace-1",
                user=SimpleNamespace(id="user-1"),
            )
        )

    assert error.value.code == code
    assert error.value.status_code == status_code


def _link_selection(document_id: str) -> dict[str, str]:
    return {
        "document_id": document_id,
        "expected_parsed_source_hash": f"parsed-{document_id}",
        "expected_analysis_run_id": f"run-{document_id}",
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


def test_profile_items_does_not_emit_cursor_past_maximum(monkeypatch):
    _patch_scope(monkeypatch)
    monkeypatch.setattr(
        disease_profiles.disease_profile_service,
        "get_items",
        lambda **_kwargs: {
            "section": "key_findings",
            "items": [
                {
                    "id": f"item-{index}",
                    "item_type": "finding",
                    "section": "key_findings",
                }
                for index in range(20)
            ],
            "total": 10_021,
        },
    )

    response = asyncio.run(
        disease_profiles.get_disease_profile_items(
            "mesh:D000795",
            workspace_id="workspace-1",
            section="key_findings",
            limit=20,
            cursor=disease_profiles._encode_cursor("10000"),
            user=SimpleNamespace(id="user-1"),
        )
    )

    assert len(response.items) == 20
    assert response.next_cursor is None


def test_profile_items_exposes_truncated_boundary(monkeypatch):
    _patch_scope(monkeypatch)
    monkeypatch.setattr(
        disease_profiles.disease_profile_service,
        "get_items",
        lambda **_kwargs: {
            "section": "key_findings",
            "items": [{"id": "item-10000", "item_type": "finding", "section": "key_findings"}],
            "total": 10_100,
            "truncated": True,
        },
    )

    response = asyncio.run(
        disease_profiles.get_disease_profile_items(
            "mesh:D000795",
            workspace_id="workspace-1",
            section="key_findings",
            limit=20,
            cursor=disease_profiles._encode_cursor("10000"),
            user=SimpleNamespace(id="user-1"),
        )
    )

    assert response.truncated is True
    assert response.next_cursor is None


def test_profile_detail_encodes_linked_document_cursor(monkeypatch):
    _patch_scope(monkeypatch)
    monkeypatch.setattr(
        disease_profiles.disease_profile_service,
        "get_profile",
        lambda **_kwargs: {
            **_summary(),
            "stats": {
                "document_count": 21,
                "research_paper_count": 21,
                "guideline_count": 0,
                "other_medical_document_count": 0,
                "valid_analysis_count": 0,
                "expired_analysis_count": 0,
                "external_article_count": 0,
                "flagged_article_count": 0,
                "comparator_reported_count": 0,
                "comparator_not_reported_count": 0,
                "human_study_count": 0,
                "animal_study_count": 0,
                "in_vitro_study_count": 0,
                "unknown_study_population_count": 0,
                "sample_size_reported_count": 0,
                "sample_size_not_reported_count": 0,
                "unknown_date_count": 0,
            },
            "documents": [],
            "documents_next_cursor": "document-020",
            "sections": [],
        },
    )

    response = asyncio.run(
        disease_profiles.get_disease_profile(
            "mesh:D000795",
            workspace_id="workspace-1",
            user=SimpleNamespace(id="user-1"),
        )
    )

    assert disease_profiles._decode_cursor(response.documents_next_cursor or "", kind="documents") == "document-020"


def test_unassigned_documents_api_forwards_page_and_encodes_cursor(monkeypatch):
    _patch_scope(monkeypatch)
    captured = {}

    def list_unassigned_documents(**kwargs):
        captured.update(kwargs)
        return {
            "items": [{
                "document_id": "document-1",
                "title": "paper.pdf",
                "document_kind": "research_paper",
                "language": "en",
                "medical_confidence": 0.9,
            }],
            "total": 21,
            "next_cursor": "document-1",
        }

    monkeypatch.setattr(
        disease_profiles.disease_profile_service,
        "list_unassigned_documents",
        list_unassigned_documents,
    )
    response = asyncio.run(
        disease_profiles.list_unassigned_disease_documents(
            workspace_id="workspace-1",
            limit=20,
            cursor=None,
            user=SimpleNamespace(id="user-1"),
        )
    )

    assert response.total == 21
    assert disease_profiles._decode_cursor(response.next_cursor or "", kind="documents") == "document-1"
    assert captured == {
        "user_id": "user-1",
        "workspace_id": "workspace-1",
        "limit": 20,
        "cursor_document_id": None,
    }


def test_external_source_documents_api_forwards_scope_and_cursor(monkeypatch):
    _patch_scope(monkeypatch)
    captured = {}

    def list_external_source_documents(**kwargs):
        captured.update(kwargs)
        if kwargs["cursor_document_id"] == "document-1":
            return {"items": [], "next_cursor": None}
        return {
            "items": [{"document_id": "document-1", "title": "paper.pdf"}],
            "next_cursor": "document-1",
        }

    monkeypatch.setattr(
        disease_profiles.disease_profile_service,
        "list_external_source_documents",
        list_external_source_documents,
    )
    response = asyncio.run(
        disease_profiles.list_disease_profile_external_source_documents(
            "mesh:D000795",
            source="pubmed",
            external_id="12345",
            workspace_id="workspace-1",
            limit=20,
            cursor=None,
            user=SimpleNamespace(id="user-1"),
        )
    )

    assert response.items[0].document_id == "document-1"
    assert disease_profiles._decode_cursor(response.next_cursor or "", kind="documents") == "document-1"
    assert captured == {
        "user_id": "user-1",
        "workspace_id": "workspace-1",
        "concept_id": "mesh:D000795",
        "source": "pubmed",
        "external_id": "12345",
        "limit": 20,
        "cursor_document_id": None,
    }

    empty_response = asyncio.run(
        disease_profiles.list_disease_profile_external_source_documents(
            "mesh:D000795",
            source="pubmed",
            external_id="12345",
            workspace_id="workspace-1",
            limit=20,
            cursor=response.next_cursor,
            user=SimpleNamespace(id="user-1"),
        )
    )
    assert empty_response.items == []
    assert empty_response.next_cursor is None


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
