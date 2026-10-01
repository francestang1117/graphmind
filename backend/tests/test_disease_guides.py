"""Tests for the public, workspace-independent disease guide contract."""

import asyncio

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from pydantic import ValidationError

from app.api.endpoints import disease_guides
from app.api.endpoints.disease_guides import (
    get_disease_guide,
    search_disease_guide_concepts,
)
from app.core.errors import AppError, register_error_handlers
from app.services.medical.disease_guide.models import DiseaseGuide
from app.services.medical.disease_guide.repository import load_guides


@pytest.fixture()
def public_guide_client() -> TestClient:
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(disease_guides.router, prefix="/api/v1")
    return TestClient(app)


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


def test_fabry_guide_uses_plain_language_topic_questions() -> None:
    guide = load_guides()[("mesh:D000795", "zh-CN")]

    assert guide.overview.text.startswith("法布雷病是一种遗传性疾病")
    assert "GLA" not in guide.overview.text
    assert [(topic.id, topic.title, topic.question) for topic in guide.topics] == [
        ("what_is", "认识疾病", "这个病是什么，为什么会发生？"),
        ("possible_impacts", "身体影响", "它可能影响身体哪些地方？"),
        ("frequency", "有多常见", "这个病有多常见？"),
        ("treatments", "治疗方向", "目前有哪些治疗方向？"),
        ("research_progress", "研究进展", "新方法研究到哪一步了？"),
    ]


def test_fabry_chaperone_entry_uses_current_japan_scope_and_label() -> None:
    guide = load_guides()[("mesh:D000795", "zh-CN")]
    treatment = next(topic for topic in guide.topics if topic.id == "treatments")
    chaperone = next(point for point in treatment.key_points if point.id == "treatment-chaperone")
    source = next(source for source in guide.sources if source.id == "pmda-galafold")

    assert str(source.url) == "https://www.pmda.go.jp/PmdaSearch/rdDetail/iyaku/3999045M1028_1?user=1"
    assert "成人和 12 岁以上儿童" in chaperone.text
    assert "特定" in chaperone.text
    assert "GLA" in chaperone.text
    assert "体重" in chaperone.qualifier
    assert "45 kg" in chaperone.qualifier
    assert source.checked_at == guide.reviewed_at


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


def test_direct_service_path_rejects_unsupported_region() -> None:
    with pytest.raises(AppError) as exc:
        asyncio.run(
            get_disease_guide("mesh:D000795", language="zh-CN", region="US")
        )

    assert exc.value.status_code == 422
    assert exc.value.code == "guide_region_not_available"


def test_public_guide_http_region_is_explicitly_limited_to_japan(public_guide_client) -> None:
    japan = public_guide_client.get(
        "/api/v1/disease-guides/mesh%3AD000795",
        params={"language": "zh-CN", "region": "JP"},
    )
    united_states = public_guide_client.get(
        "/api/v1/disease-guides/mesh%3AD000795",
        params={"language": "zh-CN", "region": "US"},
    )

    assert japan.status_code == 200
    assert japan.json()["region"] == "JP"
    assert united_states.status_code == 422
    assert united_states.json()["code"] == "guide_region_not_available"
    assert united_states.json()["details"]["available_regions"] == ["JP"]


def test_known_disease_without_a_guide_returns_a_preparing_state() -> None:
    with pytest.raises(AppError) as exc:
        asyncio.run(
            get_disease_guide("mesh:D003920", language="zh-CN", region="JP")
        )

    assert exc.value.status_code == 404
    assert exc.value.code == "disease_guide_not_ready"
