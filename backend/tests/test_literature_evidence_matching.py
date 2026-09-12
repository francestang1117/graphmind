"""Tests for deterministic finding-to-PubMed matching and its persistence boundary."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.endpoints import literature_matches
from app.core.database import Base
from app.core.errors import AppError
from app.models.persistence import (
    DocumentRecord,
    LiteratureArticleRecord,
    LiteratureEvidenceMatchRecord,
    LiteratureMatchRunRecord,
    LiteratureSearchResultRecord,
    LiteratureSearchRunRecord,
    MedicalAnalysisEvidenceRecord,
    MedicalAnalysisResultRecord,
    MedicalAnalysisRunRecord,
)
from app.services.medical.ai.models import MedicalInsightReport
from app.services.medical.evidence_matching.finding_extractor import (
    extract_matchable_findings,
)
from app.services.medical.evidence_matching.exceptions import LiteratureMatchingError
from app.services.medical.evidence_matching.matcher import locate_abstract_quote, match_articles
from app.services.medical.evidence_matching.models import MatchableFinding
from app.services.medical.evidence_matching.repository import EvidenceMatchingRepository
from app.services.medical.evidence_matching.study_card_builder import (
    build_study_card,
    classify_study_category,
    development_phase,
)


def _finding(
    finding_id: str = "finding-1",
    statement: str = "Fabry disease treatment reduced proteinuria in 42 patients.",
    *,
    condition_terms: list[str] | None = None,
    keywords: list[str] | None = None,
    phrases: list[str] | None = None,
) -> MatchableFinding:
    return MatchableFinding(
        finding_id=finding_id,
        finding_type="key_finding",
        statement=statement,
        plain_explanation="A plain-language explanation.",
        evidence_ids=["EVIDENCE_001"],
        normalized_text=statement.casefold(),
        controlled_terms=condition_terms or ["Fabry disease"],
        condition_terms=condition_terms or ["Fabry disease"],
        biomedical_terms=[],
        keywords=keywords or ["proteinuria"],
        phrases=phrases or ["reduced proteinuria"],
    )


def _article(
    external_id: str = "1001",
    *,
    title: str = "Fabry disease treatment and proteinuria outcomes",
    abstract: str | None = (
        "Fabry disease was studied in 42 patients. "
        "Proteinuria was reduced after treatment."
    ),
    mesh_terms: list[str] | None = None,
    publication_types: list[str] | None = None,
    rank: int = 1,
    retraction_status: str = "normal",
) -> dict:
    return {
        "id": f"article-{external_id}",
        "source": "pubmed",
        "external_id": external_id,
        "doi": "10.1000/example" if external_id == "1001" else None,
        "pmcid": "PMC1001" if external_id == "1001" else None,
        "title": title,
        "abstract": abstract,
        "journal": "Journal of Rare Diseases",
        "publication_year": 2024,
        "publication_types": publication_types or ["Randomized Controlled Trial"],
        "mesh_terms": mesh_terms or ["Fabry Disease"],
        "retraction_status": retraction_status,
        "source_url": f"https://pubmed.ncbi.nlm.nih.gov/{external_id}/",
        "metadata_hash": external_id.ljust(64, "a")[:64],
        "provider_rank": rank,
    }


def _report(findings: list[dict]) -> MedicalInsightReport:
    return MedicalInsightReport.model_validate(
        {
            "document_kind": "research_paper",
            "language": "en",
            "overview": {
                "title": "Fabry disease study",
                "summary": "A study report.",
                "study_type": "Research paper",
                "evidence_ids": ["EVIDENCE_001"],
            },
            "key_findings": findings,
            "limitations": [],
            "medical_terms": [],
            "what_it_means": [],
            "what_it_does_not_mean": [],
            "applicability": [],
            "future_research": [],
            "questions_for_professional": ["Could this be studied further?"],
            "warnings": [],
        }
    )


def _setup() -> tuple[sessionmaker, EvidenceMatchingRepository]:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(bind=engine)
    sessions = sessionmaker(bind=engine, autoflush=False, future=True)
    return sessions, EvidenceMatchingRepository(sessions, enabled=lambda: True)


def _document(document_id: str = "document-1", workspace_id: str = "workspace-a") -> DocumentRecord:
    return DocumentRecord(
        id=document_id,
        user_id="user-a",
        workspace_id=workspace_id,
        filename=f"{document_id}.pdf",
        stored_filename=f"{document_id}.pdf",
        original_filename="paper.pdf",
        file_extension=".pdf",
        file_type=".pdf",
        mime_type="application/pdf",
        file_hash=(document_id + "f" * 64)[:64],
        file_path=f"/tmp/{document_id}.pdf",
        file_size=10,
        status="indexed",
    )


def _analysis_and_search(
    sessions: sessionmaker,
    *,
    document_id: str = "document-1",
    workspace_id: str = "workspace-a",
    report: MedicalInsightReport | None = None,
    articles: list[dict] | None = None,
) -> tuple[str, str]:
    analysis_id = "analysis-1"
    search_id = "search-1"
    now = datetime.now(timezone.utc)
    report = report or _report(
        [
            {
                "id": "finding-1",
                "statement": "Fabry disease treatment reduced proteinuria in 42 patients.",
                "plain_explanation": "The paper reports a reduction.",
                "evidence_ids": ["EVIDENCE_001"],
                "interpretation_type": "direct_statement",
            }
        ]
    )
    articles = articles or [_article()]
    with sessions() as db:
        db.add(_document(document_id, workspace_id))
        db.add(
            MedicalAnalysisRunRecord(
                id=analysis_id,
                user_id="user-a",
                workspace_id=workspace_id,
                document_id=document_id,
                requested_by="user-a",
                status="succeeded",
                source_hash="s" * 64,
                parsed_source_hash="p" * 64,
                analysis_key="analysis-key",
                provider="extractive",
                model_name="extractive-v1",
                prompt_version="medical-insights-v2",
                schema_version="medical-insights-v2",
                is_current=True,
                created_at=now,
                completed_at=now,
                updated_at=now,
            )
        )
        db.add(
            MedicalAnalysisResultRecord(
                run_id=analysis_id,
                report_json=report.model_dump_json(),
                citation_coverage=1.0,
                validation_status="validated",
                warnings_json="[]",
                created_at=now,
            )
        )
        db.add(
            MedicalAnalysisEvidenceRecord(
                id="evidence-row-1",
                evidence_id="EVIDENCE_001",
                run_id=analysis_id,
                finding_id="finding-1",
                chunk_id="chunk-1",
                section_id="section-1",
                section_type="results",
                section_title="Results",
                page_start=3,
                page_end=3,
                quoted_text="The result was reported.",
                character_start=10,
                character_end=35,
            )
        )
        db.add(
            LiteratureSearchRunRecord(
                id=search_id,
                user_id="user-a",
                workspace_id=workspace_id,
                document_id=document_id,
                question="What is known about Fabry disease?",
                normalized_query='"Fabry disease"[Title/Abstract]',
                query_hash="q" * 64,
                provider="pubmed",
                status="succeeded",
                study_types_json="[]",
                sort="relevance",
                max_results=20,
                ontology_version="medical-ontology-v1",
                detected_concepts_json=json.dumps(
                    [
                        {
                            "type": "condition",
                            "original": "Fabry disease",
                            "normalized": "Fabry disease",
                            "concept_id": "mesh:D000795",
                            "source": "local_ontology",
                            "source_code": "D000795",
                        }
                    ]
                ),
                result_count=len(articles),
                warnings_json="[]",
                created_at=now,
                updated_at=now,
            )
        )
        for index, item in enumerate(articles, start=1):
            db.add(
                LiteratureArticleRecord(
                    id=item["id"],
                    source="pubmed",
                    external_id=item["external_id"],
                    doi=item.get("doi"),
                    pmcid=item.get("pmcid"),
                    title=item["title"],
                    abstract=item.get("abstract") or "",
                    journal=item.get("journal", ""),
                    publication_year=item.get("publication_year"),
                    publication_types_json=json.dumps(item.get("publication_types", [])),
                    mesh_terms_json=json.dumps(item.get("mesh_terms", [])),
                    language="eng",
                    source_url=item.get("source_url", ""),
                    retraction_status=item.get("retraction_status", "normal"),
                    metadata_hash=item["metadata_hash"],
                    fetched_at=now,
                    created_at=now,
                    updated_at=now,
                )
            )
            db.add(
                LiteratureSearchResultRecord(
                    id=f"search-result-{index}",
                    search_run_id=search_id,
                    article_id=item["id"],
                    provider_rank=item.get("provider_rank", index),
                    matched_terms_json="[]",
                    selected_for_analysis=False,
                    created_at=now,
                )
            )
        db.commit()
    return analysis_id, search_id


def test_finding_extractor_limits_scope_and_requires_evidence() -> None:
    finding = {
        "id": "finding-1",
        "statement": "Fabry disease treatment reduced proteinuria.",
        "plain_explanation": "A reported result.",
        "evidence_ids": ["EVIDENCE_001"],
    }
    report = _report(
        [
            finding,
            {**finding, "id": "no-evidence", "evidence_ids": []},
            {**finding, "id": "duplicate"},
        ]
    )

    extracted = extract_matchable_findings(
        report,
        detected_concepts=[
            {
                "type": "condition",
                "normalized": "Fabry disease",
                "concept_id": "mesh:D000795",
            }
        ],
        valid_evidence_ids={"EVIDENCE_001"},
    )

    assert len(extracted) == 1
    assert extracted[0].finding_type == "key_finding"
    assert extracted[0].condition_terms == ["Fabry disease"]
    assert "questions_for_professional" not in extracted[0].statement


def test_finding_extractor_processes_at_most_twenty_findings() -> None:
    report = _report(
        [
            {
                "id": f"finding-{index}",
                "statement": f"The treatment changed biomarker {index}.",
                "plain_explanation": "A reported result.",
                "evidence_ids": ["EVIDENCE_001"],
            }
            for index in range(25)
        ]
    )
    assert len(extract_matchable_findings(report, max_findings=20)) == 20


def test_matcher_scores_specific_matches_and_locates_exact_abstract_text() -> None:
    article = _article()
    result = match_articles([_finding()], [article])

    card = result.findings[0].candidates[0]
    assert result.findings[0].match_status == "matched"
    assert card.match_specificity == "finding_specific"
    assert 40 <= card.relevance_score <= 100
    expected_quote = article["abstract"].split(". ")[1]
    expected_start = article["abstract"].index(expected_quote)
    assert card.abstract_quote == expected_quote
    assert article["abstract"][card.abstract_character_start : card.abstract_character_end] == card.abstract_quote
    assert card.abstract_character_start == expected_start
    assert card.abstract_character_end == expected_start + len(expected_quote)
    assert card.source_url.endswith("/1001/")


def test_quote_offsets_use_original_unicode_text_positions() -> None:
    abstract = "The ß marker is present. Fabry disease was studied in patients."

    quote, start, end = locate_abstract_quote(abstract, ["fabry disease"])

    assert quote == "Fabry disease was studied in patients."
    assert abstract[start:end] == quote


def test_condition_only_is_explicit_and_not_finding_specific() -> None:
    article = _article(
        title="Fabry disease registry",
        abstract="A public registry abstract.",
        mesh_terms=["Fabry Disease"],
    )
    result = match_articles(
        [_finding(keywords=["proteinuria"], phrases=["reduced proteinuria"])],
        [article],
    )

    assert result.findings[0].match_status == "condition_only"
    assert result.findings[0].candidates[0].match_specificity == "condition_only"
    assert result.findings[0].candidates[0].abstract_quote is None


def test_matcher_excludes_retractions_and_reports_empty_eligible_result() -> None:
    result = match_articles(
        [_finding()],
        [_article(retraction_status="retracted"), _article("1002", retraction_status="retraction_notice")],
    )

    assert result.match_count == 0
    assert result.article_count == 0
    assert result.empty_reason == "no_eligible_articles"
    assert result.excluded_articles == {"retracted": 1, "retraction_notice": 1}


def test_matcher_is_bounded_and_deterministic() -> None:
    articles = [
        _article(str(2000 + index), title="Fabry disease registry", rank=10 - index)
        for index in range(10)
    ]
    first = match_articles([_finding()], articles, max_articles=3, max_per_finding=2)
    second = match_articles([_finding()], list(reversed(articles)), max_articles=3, max_per_finding=2)

    first_ids = [card.pmid for card in first.findings[0].candidates]
    second_ids = [card.pmid for card in second.findings[0].candidates]
    assert len(first_ids) == 2
    assert first_ids == second_ids
    assert all(card.relevance_score <= 100 for card in first.findings[0].candidates)


def test_matcher_uses_numeric_pmid_order_for_tied_provider_ranks() -> None:
    articles = [
        _article("2", title="Fabry disease registry", rank=1),
        _article("10", title="Fabry disease registry", rank=1),
    ]

    result = match_articles([_finding()], articles, max_articles=2, max_per_finding=2)

    assert [card.pmid for card in result.findings[0].candidates] == ["2", "10"]


def test_matcher_does_not_translate_arbitrary_chinese_text() -> None:
    finding = MatchableFinding(
        finding_id="finding-zh",
        finding_type="key_finding",
        statement="该研究报告了罕见病患者的结果。",
        plain_explanation="原文结果。",
        evidence_ids=["EVIDENCE_001"],
        normalized_text="该研究报告了罕见病患者的结果。",
        controlled_terms=[],
        condition_terms=[],
        biomedical_terms=[],
        keywords=[],
        phrases=[],
    )
    result = match_articles([finding], [_article()])
    assert result.findings[0].match_status == "insufficient_terms"
    assert result.match_count == 0


def test_study_card_uses_only_pubmed_publication_types() -> None:
    assert classify_study_category(["Randomized Controlled Trial"]) == "randomized_controlled_trial"
    assert classify_study_category(["Clinical Trial"]) == "clinical_trial"
    assert development_phase(["Clinical Trial"]) == "not_reported"
    assert development_phase(["Phase 3", "Clinical Trial"]) == "phase_3"

    card = build_study_card(
        _article(publication_types=["Clinical Trial"]),
        relevance_score=42,
        match_specificity="finding_specific",
        matched_terms=["Fabry disease"],
        match_reasons=["Title overlap"],
    )
    assert card.study_category == "clinical_trial"
    assert card.development_phase == "not_reported"
    assert "potentially relevant" in card.warnings[0]
    assert "does not mean" in card.warnings[1]


def test_study_card_warns_on_status_and_missing_abstract() -> None:
    card = build_study_card(
        _article(
            abstract=None,
            retraction_status="expression_of_concern",
            publication_types=["Systematic Review"],
        ),
        relevance_score=40,
        match_specificity="condition_only",
    )
    assert card.study_category == "systematic_review"
    assert card.abstract_available is False
    assert any("expression of concern" in warning for warning in card.warnings)
    assert any("abstract" in warning.lower() for warning in card.warnings)


def test_repository_persists_and_reuses_scoped_match_run() -> None:
    sessions, repository = _setup()
    analysis_id, search_id = _analysis_and_search(sessions)

    first, created = repository.create_or_reuse_match_run(
        document_id="document-1",
        user_id="user-a",
        workspace_id="workspace-a",
        analysis_run_id=analysis_id,
        search_run_id=search_id,
    )
    second, reused = repository.create_or_reuse_match_run(
        document_id="document-1",
        user_id="user-a",
        workspace_id="workspace-a",
        analysis_run_id=analysis_id,
        search_run_id=search_id,
    )

    assert created is True
    assert reused is False
    assert first["match_run_id"] == second["match_run_id"]
    assert first["summary"]["match_count"] == 1
    assert second["findings"][0]["candidates"][0]["pmid"] == "1001"
    with sessions() as db:
        assert db.scalar(select(func.count(LiteratureMatchRunRecord.id))) == 1
        assert db.scalar(select(func.count(LiteratureEvidenceMatchRecord.id))) == 1


def test_repository_marks_article_metadata_changes_as_stale() -> None:
    sessions, repository = _setup()
    analysis_id, search_id = _analysis_and_search(sessions)
    saved, _ = repository.create_or_reuse_match_run(
        document_id="document-1",
        user_id="user-a",
        workspace_id="workspace-a",
        analysis_run_id=analysis_id,
        search_run_id=search_id,
    )
    with sessions() as db:
        article = db.get(LiteratureArticleRecord, "article-1001")
        article.metadata_hash = "b" * 64
        db.commit()

    current = repository.get_match_run(saved["match_run_id"], "user-a", "workspace-a")
    assert current["stale"] is True
    assert current["findings"][0]["candidates"][0]["stale"] is True
    assert "article_metadata_changed" in current["warnings"]


def test_repository_rejects_cross_workspace_inputs() -> None:
    sessions, repository = _setup()
    analysis_id, search_id = _analysis_and_search(sessions, workspace_id="workspace-a")

    with pytest.raises(LiteratureMatchingError) as exc:
        repository.create_or_reuse_match_run(
            document_id="document-1",
            user_id="user-a",
            workspace_id="workspace-b",
            analysis_run_id=analysis_id,
            search_run_id=search_id,
        )
    assert exc.value.code == "literature_match_scope_mismatch"


def test_repository_requires_validated_analysis_and_evidence() -> None:
    sessions, repository = _setup()
    analysis_id, search_id = _analysis_and_search(sessions)
    with sessions() as db:
        db.get(MedicalAnalysisResultRecord, analysis_id).validation_status = "rejected"
        db.commit()

    with pytest.raises(LiteratureMatchingError) as exc:
        repository.create_or_reuse_match_run(
            document_id="document-1",
            user_id="user-a",
            workspace_id="workspace-a",
            analysis_run_id=analysis_id,
            search_run_id=search_id,
        )
    assert exc.value.code == "medical_analysis_not_validated"


def test_repository_deletes_match_rows_for_soft_deleted_document_cleanup() -> None:
    sessions, repository = _setup()
    analysis_id, search_id = _analysis_and_search(sessions)
    saved, _ = repository.create_or_reuse_match_run(
        document_id="document-1",
        user_id="user-a",
        workspace_id="workspace-a",
        analysis_run_id=analysis_id,
        search_run_id=search_id,
    )
    repository.delete_for_document("document-1", "user-a", "workspace-a")

    assert repository.get_match_run(saved["match_run_id"], "user-a", "workspace-a") is None
    with sessions() as db:
        assert db.scalar(select(func.count(LiteratureEvidenceMatchRecord.id))) == 0


def test_repository_returns_no_findings_for_report_without_evidence() -> None:
    sessions, repository = _setup()
    report = _report(
        [
            {
                "id": "finding-no-evidence",
                "statement": "A result without a source.",
                "plain_explanation": "No source.",
                "evidence_ids": [],
            }
        ]
    )
    analysis_id, search_id = _analysis_and_search(sessions, report=report)

    with pytest.raises(LiteratureMatchingError) as exc:
        repository.create_or_reuse_match_run(
            document_id="document-1",
            user_id="user-a",
            workspace_id="workspace-a",
            analysis_run_id=analysis_id,
            search_run_id=search_id,
        )
    assert exc.value.code == "literature_match_no_findings"


def test_api_returns_201_then_200_for_new_and_reused_run(monkeypatch) -> None:
    monkeypatch.setattr(literature_matches, "resolve_workspace_id", lambda *_args: "workspace-a")
    monkeypatch.setattr(
        literature_matches.document_service,
        "get_document_by_id",
        lambda document_id, user_id, workspace_id=None: {
            "document_id": document_id,
            "user_id": user_id,
            "workspace_id": workspace_id,
        },
    )
    calls = iter(
        [
            ({"match_run_id": "run-1", "status": "completed"}, True),
            ({"match_run_id": "run-1", "status": "completed"}, False),
        ]
    )

    class FakeRepository:
        def available(self):
            return True

        def create_or_reuse_match_run(self, **_kwargs):
            return next(calls)

    monkeypatch.setattr(literature_matches, "evidence_matching_repository", FakeRepository())
    body = literature_matches.LiteratureMatchRequest(
        analysis_run_id="analysis-1",
        search_run_id="search-1",
    )
    first = asyncio.run(
        literature_matches.create_literature_match(
            "document-1",
            body,
            workspace_id="workspace-a",
            user=SimpleNamespace(id="user-a"),
        )
    )
    second = asyncio.run(
        literature_matches.create_literature_match(
            "document-1",
            body,
            workspace_id="workspace-a",
            user=SimpleNamespace(id="user-a"),
        )
    )
    assert first.status_code == 201
    assert second.status_code == 200


def test_api_hides_missing_match_run_as_not_found(monkeypatch) -> None:
    monkeypatch.setattr(literature_matches, "resolve_workspace_id", lambda *_args: "workspace-a")

    class FakeRepository:
        def available(self):
            return True

        def get_match_run(self, *_args):
            return None

    monkeypatch.setattr(literature_matches, "evidence_matching_repository", FakeRepository())
    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            literature_matches.get_literature_match(
                "missing",
                workspace_id="workspace-a",
                user=SimpleNamespace(id="user-a"),
            )
        )
    assert exc.value.status_code == 404


def test_api_maps_not_ready_to_conflict(monkeypatch) -> None:
    monkeypatch.setattr(literature_matches, "resolve_workspace_id", lambda *_args: "workspace-a")
    monkeypatch.setattr(
        literature_matches.document_service,
        "get_document_by_id",
        lambda document_id, user_id, workspace_id=None: {"document_id": document_id},
    )

    class FakeRepository:
        def available(self):
            return True

        def create_or_reuse_match_run(self, **_kwargs):
            raise LiteratureMatchingError("not ready", code="medical_analysis_not_ready")

    monkeypatch.setattr(literature_matches, "evidence_matching_repository", FakeRepository())
    with pytest.raises(AppError) as exc:
        asyncio.run(
            literature_matches.create_literature_match(
                "document-1",
                literature_matches.LiteratureMatchRequest(
                    analysis_run_id="analysis-1",
                    search_run_id="search-1",
                ),
                workspace_id="workspace-a",
                user=SimpleNamespace(id="user-a"),
            )
        )
    assert exc.value.status_code == 409
    assert exc.value.code == "medical_analysis_not_ready"
