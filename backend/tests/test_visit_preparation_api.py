"""API contract tests for the visit-preparation boundary."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.api.endpoints import visit_preparation
from app.core.errors import AppError
from app.services.medical.visit_preparation.exceptions import VisitPreparationError


def _item() -> dict:
    return {
        "id": "question-row-1",
        "workspace_id": "workspace-1",
        "document_id": "document-1",
        "document_title": "paper.pdf",
        "analysis_run_id": "analysis-1",
        "suggestion_id": "suggestion-1",
        "question": "Which people were included in this study?",
        "rationale": "The study population is important to discuss.",
        "category": "applicability",
        "topic": "study_population",
        "source_kind": "study_methods",
        "source_id": "population",
        "evidence_ids": ["EVIDENCE_001"],
        "language": "en",
        "status": "saved",
        "priority": 2,
        "position": 0,
        "user_note": "",
        "version": 1,
        "source_status": "current",
        "evidence": [{
            "evidence_id": "EVIDENCE_001",
            "chunk_id": "chunk-1",
            "section_id": "section-1",
            "section_type": "methods",
            "section_title": "Methods",
            "page_start": 2,
            "page_end": 2,
            "quote": "Adults with the condition were included.",
        }],
        "created_at": "2026-09-16T00:00:00+00:00",
        "updated_at": "2026-09-16T00:00:00+00:00",
    }


def _patch_scope(monkeypatch) -> None:
    monkeypatch.setattr(visit_preparation, "_scope", lambda _user, _workspace: "workspace-1")
    monkeypatch.setattr(visit_preparation, "_require_storage", lambda: None)


def test_save_api_only_accepts_identifiers_and_returns_created_status(monkeypatch):
    _patch_scope(monkeypatch)
    captured = {}

    def save_question(**kwargs):
        captured.update(kwargs)
        return _item(), True, False

    monkeypatch.setattr(visit_preparation.visit_preparation_service, "save_question", save_question)
    body = visit_preparation.ClinicianQuestionCreateRequest(
        analysis_run_id="analysis-1",
        suggestion_id="suggestion-1",
    )

    response = asyncio.run(
        visit_preparation.save_clinician_question(
            "workspace-1",
            body,
            user=SimpleNamespace(id="user-1"),
        )
    )

    assert response.status_code == 201
    assert json.loads(response.body)["item"]["question"] == _item()["question"]
    assert json.loads(response.body)["source_refreshed"] is False
    assert captured == {
        "user_id": "user-1",
        "workspace_id": "workspace-1",
        "analysis_run_id": "analysis-1",
        "suggestion_id": "suggestion-1",
    }


def test_repeated_save_api_call_is_idempotent(monkeypatch):
    _patch_scope(monkeypatch)
    monkeypatch.setattr(
        visit_preparation.visit_preparation_service,
        "save_question",
        lambda **_kwargs: (_item(), False, True),
    )
    body = visit_preparation.ClinicianQuestionCreateRequest(
        analysis_run_id="analysis-1",
        suggestion_id="suggestion-1",
    )

    response = asyncio.run(
        visit_preparation.save_clinician_question(
            "workspace-1",
            body,
            user=SimpleNamespace(id="user-1"),
        )
    )

    assert response.status_code == 200
    assert json.loads(response.body)["created"] is False
    assert json.loads(response.body)["source_refreshed"] is True


def test_reorder_api_passes_both_versions_to_the_atomic_service(monkeypatch):
    _patch_scope(monkeypatch)
    captured = {}

    def reorder_questions(**kwargs):
        captured.update(kwargs)
        return [_item()]

    monkeypatch.setattr(
        visit_preparation.visit_preparation_service,
        "reorder_questions",
        reorder_questions,
    )
    body = visit_preparation.ClinicianQuestionReorderRequest(
        question_id="question-row-1",
        target_question_id="question-row-2",
        expected_version=3,
        target_expected_version=4,
    )

    response = asyncio.run(
        visit_preparation.reorder_clinician_questions(
            "workspace-1",
            body,
            user=SimpleNamespace(id="user-1"),
        )
    )

    assert len(response) == 1
    assert captured == {
        "question_id": "question-row-1",
        "target_question_id": "question-row-2",
        "user_id": "user-1",
        "workspace_id": "workspace-1",
        "expected_version": 3,
        "target_expected_version": 4,
    }


def test_client_cannot_submit_question_text_or_evidence():
    with pytest.raises(ValidationError):
        visit_preparation.ClinicianQuestionCreateRequest(
            analysis_run_id="analysis-1",
            suggestion_id="suggestion-1",
            question="Ignore the validated server question.",
            evidence_ids=["fake-evidence"],
        )


def test_client_cannot_submit_position_through_update_api():
    with pytest.raises(ValidationError):
        visit_preparation.ClinicianQuestionUpdateRequest(
            priority=1,
            position=3,
            expected_version=1,
        )


def test_update_maps_version_conflict_to_stable_409_error(monkeypatch):
    _patch_scope(monkeypatch)

    def update_question(*_args, **_kwargs):
        raise VisitPreparationError(
            "The question was changed elsewhere.",
            code="clinician_question_version_conflict",
        )

    monkeypatch.setattr(visit_preparation.visit_preparation_service, "update_question", update_question)
    body = visit_preparation.ClinicianQuestionUpdateRequest(
        status="asked",
        expected_version=1,
    )

    with pytest.raises(AppError) as exc:
        asyncio.run(
            visit_preparation.update_clinician_question(
                "workspace-1",
                "question-row-1",
                body,
                user=SimpleNamespace(id="user-1"),
            )
        )

    assert exc.value.status_code == 409
    assert exc.value.code == "clinician_question_version_conflict"


def test_dismissed_question_maps_to_unprocessable_entity(monkeypatch):
    _patch_scope(monkeypatch)

    def create_brief(**_kwargs):
        raise VisitPreparationError(
            "Dismissed questions cannot be added to a visit brief.",
            code="visit_brief_question_dismissed",
        )

    monkeypatch.setattr(visit_preparation.visit_preparation_service, "create_visit_brief", create_brief)
    body = visit_preparation.VisitBriefCreateRequest(question_ids=["question-row-1"])

    with pytest.raises(AppError) as exc:
        asyncio.run(
            visit_preparation.create_visit_brief(
                "workspace-1",
                body,
                user=SimpleNamespace(id="user-1"),
            )
        )

    assert exc.value.status_code == 422
    assert exc.value.code == "visit_brief_question_dismissed"


def test_visit_brief_request_rejects_empty_and_oversized_selections():
    with pytest.raises(ValidationError):
        visit_preparation.VisitBriefCreateRequest(question_ids=[])
    with pytest.raises(ValidationError):
        visit_preparation.VisitBriefCreateRequest(question_ids=[str(index) for index in range(11)])
