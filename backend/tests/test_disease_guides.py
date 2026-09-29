"""Tests for the public, workspace-independent disease guide contract."""

import asyncio

import pytest
from pydantic import ValidationError

from app.api.endpoints.disease_guides import (
    get_disease_guide,
    search_disease_guide_concepts,
)
from app.core.errors import AppError
from app.services.medical.disease_guide.models import DiseaseGuide
from app.services.medical.disease_guide.repository import load_guides


def test_fabry_guide_has_sources_and_review_dates_for_every_claim() -> None:
    guide = load_guides()[("mesh:D000795", "zh-CN")]
    source_ids = {source.id for source in guide.sources}

    assert guide.reviewed_at
    assert len(guide.topics) == 5
    assert guide.overview.source_ids
    assert all(source.checked_at for source in guide.sources)
    for topic in guide.topics:
        assert topic.summary.source_ids
        for point in topic.key_points:
            assert set(point.source_ids) <= source_ids
            if topic.id in {"treatments", "research_progress"}:
                assert point.evidence_stage
            if topic.id == "treatments":
                assert point.region == "JP"


def test_guide_rejects_a_claim_that_references_an_unknown_source() -> None:
    payload = load_guides()[("mesh:D000795", "zh-CN")].model_dump(mode="json")
    payload["overview"]["source_ids"] = ["source-that-does-not-exist"]

    with pytest.raises(ValidationError, match="unknown sources"):
        DiseaseGuide.model_validate(payload)


def test_public_search_resolves_chinese_and_english_aliases_to_one_concept() -> None:
    chinese = asyncio.run(search_disease_guide_concepts(q="法布雷病", limit=5))
    english = asyncio.run(search_disease_guide_concepts(q="Fabry", limit=5))

    assert chinese.items[0].concept_id == "mesh:D000795"
    assert english.items[0].concept_id == chinese.items[0].concept_id
    assert chinese.items[0].guide_status == "available"
    assert chinese.items[0].guide_languages == ["zh-CN"]


def test_public_guide_does_not_require_a_workspace_or_private_documents() -> None:
    guide = asyncio.run(
        get_disease_guide("mesh:D000795", language="zh-CN", region="JP")
    )
    payload = guide.model_dump()

    assert payload["concept_id"] == "mesh:D000795"
    assert payload["region_status"] == "verified"
    assert "workspace_id" not in payload
    assert "documents" not in payload
    assert "analyses" not in payload


def test_unverified_region_is_explicitly_marked_instead_of_inventing_approval_status() -> None:
    guide = asyncio.run(
        get_disease_guide("mesh:D000795", language="zh-CN", region="US")
    )

    assert guide.region == "US"
    assert guide.region_status == "not_verified"
    assert "US" in guide.region_note
    assert "未知" in guide.region_note


def test_known_disease_without_a_guide_returns_a_preparing_state() -> None:
    with pytest.raises(AppError) as exc:
        asyncio.run(
            get_disease_guide("mesh:D003920", language="zh-CN", region="JP")
        )

    assert exc.value.status_code == 404
    assert exc.value.code == "disease_guide_not_ready"
