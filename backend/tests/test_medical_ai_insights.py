"""Tests for evidence-backed medical document insights."""

from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
import json
import os
import threading
from types import SimpleNamespace
import uuid

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.persistence import (
    DocumentRecord,
    DocumentSectionRecord,
    MedicalAnalysisEvidenceRecord,
    MedicalAnalysisRunRecord,
    MedicalDocumentProfileRecord,
    ParsedChunkRecord,
)
from app.services.medical.ai.analysis_repository import AnalysisRepository
from app.services.medical.ai.analyzer import MedicalInsightAnalyzer
from app.services.medical.ai.citation_validator import evidence_rows, validate_citations
from app.services.medical.ai.context_builder import (
    AnalysisContext,
    ContextBuilder,
    EvidenceItem,
    _estimate_tokens,
    _truncate_text,
    redact_sensitive_fields,
)
from app.services.medical.ai.exceptions import MedicalInsightError, MedicalInsightValidationError
from app.services.medical.ai.models import MedicalInsightReport
from app.services.medical.ai.provider import (
    ExtractiveMedicalAIProvider,
    FakeMedicalAIProvider,
    OpenAIMedicalAIProvider,
)
from app.services.medical.ai.safety_validator import validate_safety
from app.services.medical.ai.support_validator import validate_support


def _context(*items: tuple[str, str]) -> AnalysisContext:
    evidence = [
        EvidenceItem(
            evidence_id=evidence_id,
            chunk_id=f"chunk-{index}",
            section_id=f"section-{index}",
            section_type=section_type,
            section_title=section_type.title(),
            page_start=index,
            page_end=index,
            character_start=index * 100,
            character_end=index * 100 + 20,
            text=f"Source text for {evidence_id}.",
            token_count=5,
            source_index=index,
        )
        for index, (evidence_id, section_type) in enumerate(items, start=1)
    ]
    return AnalysisContext(
        title="Example paper",
        document_kind="research_paper",
        language="en",
        evidence=evidence,
    )


def _report(*evidence_ids: str) -> MedicalInsightReport:
    return MedicalInsightReport.model_validate(
        {
            "document_kind": "research_paper",
            "language": "en",
            "overview": {
                "title": "Example paper",
                "summary": "The paper reports a result.",
                "study_type": "Research paper",
                "evidence_ids": list(evidence_ids[:1]),
            },
            "key_findings": [
                {
                    "id": "finding_001",
                    "statement": "The paper reports a result.",
                    "plain_explanation": "This is what the paper says.",
                    "evidence_ids": list(evidence_ids[:1]),
                    "evidence_level": "reported_in_document",
                    "interpretation_type": "direct_statement",
                }
            ],
            "limitations": [],
            "medical_terms": [],
            "what_it_means": [],
            "what_it_does_not_mean": [],
            "questions_for_professional": [],
            "warnings": [],
        }
    )


def test_citations_require_current_evidence_and_reject_references():
    context = _context(("EVIDENCE_001", "results"), ("EVIDENCE_002", "references"))

    valid = validate_citations(_report("EVIDENCE_001"), context)
    assert valid.valid
    assert valid.coverage == 1.0
    assert evidence_rows(_report("EVIDENCE_001"), context)[0]["section_type"] == "results"

    references = validate_citations(_report("EVIDENCE_002"), context)
    assert not references.valid
    assert any("references section" in error for error in references.errors)

    unknown = validate_citations(_report("EVIDENCE_999"), context)
    assert not unknown.valid
    assert any("unknown evidence id" in error for error in unknown.errors)


def test_safety_validator_rejects_personal_treatment_instructions():
    payload = _report("EVIDENCE_001").model_dump()
    payload["key_findings"] = [
        {
            "id": "finding_001",
            "statement": "You should change your medication.",
            "plain_explanation": "This is not allowed in a document summary.",
            "evidence_ids": ["EVIDENCE_001"],
            "evidence_level": "reported_in_document",
            "interpretation_type": "inference",
        }
    ]
    report = MedicalInsightReport.model_validate(payload)
    validation = validate_safety(report)
    assert not validation.valid
    assert "treatment" in validation.errors[0]


def test_safety_validator_checks_questions_and_chinese_diagnosis_text():
    payload = _report("EVIDENCE_001").model_dump()
    payload["questions_for_professional"] = ["你应该停药吗？"]
    report = MedicalInsightReport.model_validate(payload)

    validation = validate_safety(report)

    assert not validation.valid
    assert any("treatment" in error for error in validation.errors)

    payload["questions_for_professional"] = []
    payload["medical_terms"] = [
        {
            "term": "你可能患有糖尿病",
            "explanation": "This text must not be shown as a confirmed diagnosis.",
            "evidence_ids": [],
        }
    ]
    report = MedicalInsightReport.model_validate(payload)

    assert not validate_safety(report).valid


def test_safety_validator_allows_descriptive_medical_language():
    payload = _report("EVIDENCE_001").model_dump()
    payload["overview"]["summary"] = "The paper describes medication use and treatment outcomes."
    payload["questions_for_professional"] = [
        "What medication and treatment outcomes did the authors report?"
    ]

    assert validate_safety(MedicalInsightReport.model_validate(payload)).valid


def test_context_builder_reads_legacy_page_metadata_for_guidelines():
    context = ContextBuilder().build(
        [
            {
                "id": "chunk-1",
                "text": "The guideline recommends shared decision-making.",
                "chunk_type": "page",
                "metadata": {
                    "type": "page",
                    "page": 4,
                    "section_type": "recommendations",
                    "section_title": "Recommendations",
                },
            }
        ],
        title="Clinical guideline",
        document_kind="guideline",
        language="en",
    )

    evidence = context.evidence[0]
    assert evidence.section_type == "recommendations"
    assert evidence.section_title == "Recommendations"
    assert evidence.page_start == evidence.page_end == 4


def test_context_builder_preserves_safe_parser_warnings_only():
    context = ContextBuilder().build(
        [{"id": "chunk-1", "text": "A table was extracted.", "section_type": "table"}],
        source_warnings=[
            "table_location_unavailable",
            "Contains source text: Patient Name",
            "table_location_unavailable",
        ],
    )

    assert context.warnings == ["table_location_unavailable"]


def test_context_builder_counts_and_truncates_cjk_text_without_rebuilding_it():
    source = "中文医学论文内容" * 200

    assert _estimate_tokens(source) > 100

    truncated = _truncate_text(source, 100)

    assert _estimate_tokens(truncated) <= 100
    assert truncated.startswith("中文医学")
    assert truncated.endswith(" …")

    context = ContextBuilder().build(
        [{"id": "chunk-1", "text": source, "section_type": "results"}],
        title="中文论文",
        document_kind="research_paper",
        language="zh",
        max_input_tokens=100,
    )
    assert context.evidence[0].token_count <= 100


def test_context_builder_reserves_space_across_paper_sections():
    chunks = [
        {
            "id": f"chunk-{section}",
            "text": f"{section} " + ("source text " * 80),
            "section_type": section,
        }
        for section in ("introduction", "methods", "results", "discussion", "limitations")
    ]

    context = ContextBuilder().build(
        chunks,
        title="Long paper",
        document_kind="research_paper",
        language="en",
        max_input_tokens=220,
    )

    assert set(context.included_sections) == {
        "introduction",
        "methods",
        "results",
        "discussion",
        "limitations",
    }
    assert context.omitted_sections == []
    assert context.total_chunks == 5
    assert sum(item.token_count for item in context.evidence) <= 220
    assert "context_truncated" in context.warnings


class _Responses:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return SimpleNamespace(output_text=outcome)


class _OpenAIClient:
    def __init__(self, outcomes):
        self.responses = _Responses(outcomes)


def test_openai_provider_uses_responses_structured_output_without_storage():
    payload = _report("EVIDENCE_001").model_dump()
    client = _OpenAIClient([json.dumps(payload)])
    provider = OpenAIMedicalAIProvider(
        api_key="test-key",
        model_name="test-model",
        max_output_tokens=700,
        retry_count=0,
        client=client,
    )

    result = provider.generate("prompt", _context(("EVIDENCE_001", "results")))

    assert json.loads(result)["overview"]["title"] == "Example paper"
    call = client.responses.calls[0]
    assert call["model"] == "test-model"
    assert call["max_output_tokens"] == 700
    assert call["store"] is False
    assert 0 < call["timeout"] <= provider.timeout_seconds
    schema = call["text"]["format"]["schema"]
    assert schema["additionalProperties"] is False
    assert "study_methods" in schema["required"]
    assert "future_research" in schema["required"]


def test_openai_provider_retries_rate_limits_without_logging_source():
    rate_limit = RuntimeError("rate limited")
    rate_limit.status_code = 429
    payload = json.dumps(_report("EVIDENCE_001").model_dump())
    client = _OpenAIClient([rate_limit, payload])
    delays = []
    provider = OpenAIMedicalAIProvider(
        api_key="test-key",
        model_name="test-model",
        retry_count=1,
        client=client,
        sleep=delays.append,
    )

    assert provider.generate("private source", _context(("EVIDENCE_001", "results"))) == payload
    assert len(client.responses.calls) == 2
    assert delays == [1]


def test_openai_provider_reports_timeout_after_bounded_retries():
    client = _OpenAIClient([TimeoutError(), TimeoutError()])
    provider = OpenAIMedicalAIProvider(
        api_key="test-key",
        model_name="test-model",
        retry_count=1,
        client=client,
        sleep=lambda _delay: None,
    )

    with pytest.raises(MedicalInsightError) as exc:
        provider.generate("prompt", _context(("EVIDENCE_001", "results")))

    assert exc.value.code == "provider_timeout"
    assert len(client.responses.calls) == 2


def test_openai_invalid_json_gets_one_schema_repair_attempt():
    valid = json.dumps(_report("EVIDENCE_001").model_dump())
    client = _OpenAIClient(["not-json", valid])
    provider = OpenAIMedicalAIProvider(
        api_key="test-key",
        model_name="test-model",
        retry_count=0,
        client=client,
    )

    output = MedicalInsightAnalyzer(provider=provider).run(
        [{"id": "chunk-1", "text": "The result was reported.", "section_type": "results"}],
        title="Example paper",
        document_kind="research_paper",
        language="en",
    )

    assert output.citations.valid
    assert output.support.valid
    assert len(client.responses.calls) == 2
    assert "previous output failed" in client.responses.calls[1]["input"]


@pytest.mark.parametrize(
    ("source", "claim", "expected"),
    [
        (
            "Treatment was associated with lower risk.",
            "Treatment caused lower risk.",
            "association into causation",
        ),
        (
            "In vitro cell experiments showed reduced growth.",
            "The treatment was effective in patients.",
            "preclinical evidence into human efficacy",
        ),
        (
            "There was no statistically significant difference between groups.",
            "The treatment was proven ineffective.",
            "proof of no effect",
        ),
        (
            "The intervention may reduce symptoms in 20 patients.",
            "The intervention proves symptoms are reduced in 40 patients.",
            "numbers or units",
        ),
    ],
)
def test_support_validator_rejects_overstated_claims(source, claim, expected):
    context = _context(("EVIDENCE_001", "results"))
    context.evidence[0] = EvidenceItem(
        **{**context.evidence[0].__dict__, "text": source}
    )
    payload = _report("EVIDENCE_001").model_dump()
    payload["key_findings"][0]["statement"] = claim
    report = MedicalInsightReport.model_validate(payload)

    validation = validate_support(report, context)

    assert not validation.valid
    assert any(expected in error for error in validation.errors)


def test_redact_sensitive_fields_removes_chinese_and_english_names():
    redacted, changed = redact_sensitive_fields(
        "姓名：张三\n患者姓名 : 李四\nName: Alice\naddress: 1 Main Street"
    )

    assert changed
    assert "张三" not in redacted
    assert "李四" not in redacted
    assert "Alice" not in redacted
    assert "1 Main Street" not in redacted
    assert "[REDACTED]" in redacted


def test_context_builder_redacts_title_and_section_title():
    context = ContextBuilder().build(
        [
            {
                "id": "chunk-1",
                "text": "The study reports the observed outcome.",
                "section_type": "results",
                "section_title": "患者姓名：李四",
                "page": 2,
            }
        ],
        title="姓名：张三的检查报告",
        document_kind="research_paper",
        language="zh",
    )

    assert "张三" not in context.title
    assert "李四" not in context.evidence[0].section_title
    assert "pii_redacted" in context.warnings


def test_analyzer_repairs_one_invalid_provider_response():
    invalid = _report("EVIDENCE_001").model_dump()
    invalid["overview"]["evidence_ids"] = []
    valid = _report("EVIDENCE_001").model_dump()
    provider = FakeMedicalAIProvider(payloads=[invalid, valid])

    output = MedicalInsightAnalyzer(provider=provider).run(
        [{"id": "chunk-1", "text": "The result was reported.", "metadata": {"section_type": "results"}}],
        title="Example paper",
        document_kind="research_paper",
        language="en",
    )

    assert output.citations.valid
    assert len(provider.calls) == 2
    assert output.report.warnings[-1] == "not_medical_advice"


def test_analyzer_exposes_parser_warnings_in_the_report():
    provider = FakeMedicalAIProvider(payloads=[_report("EVIDENCE_001").model_dump()])

    output = MedicalInsightAnalyzer(provider=provider).run(
        [{"id": "chunk-1", "text": "The result was reported.", "section_type": "results"}],
        source_warnings=["table_location_unavailable"],
        title="Example paper",
        document_kind="research_paper",
        language="en",
    )

    assert "table_location_unavailable" in output.report.warnings


def test_analyzer_does_not_retry_more_than_once_after_invalid_repair():
    invalid = _report("EVIDENCE_001").model_dump()
    invalid["overview"]["evidence_ids"] = []
    provider = FakeMedicalAIProvider(payloads=[invalid, invalid, invalid])

    with pytest.raises(MedicalInsightValidationError):
        MedicalInsightAnalyzer(provider=provider).run(
            [{"id": "chunk-1", "text": "The result was reported.", "metadata": {"section_type": "results"}}],
            title="Example paper",
            document_kind="research_paper",
            language="en",
        )

    assert len(provider.calls) == 2


def _repository():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(bind=engine)
    sessions = sessionmaker(bind=engine, autoflush=False, future=True)
    return engine, sessions, AnalysisRepository(sessions, enabled=lambda: True)


def _paper_rows(sessions):
    now = datetime.now(timezone.utc)
    with sessions() as db:
        db.add(
            DocumentRecord(
                id="document-1",
                user_id="user-1",
                workspace_id="workspace-1",
                filename="paper.pdf",
                stored_filename="paper.pdf",
                original_filename="paper.pdf",
                file_extension=".pdf",
                file_type=".pdf",
                mime_type="application/pdf",
                file_hash="a" * 64,
                file_path="/tmp/paper.pdf",
                file_size=100,
                status="indexed",
                created_at=now,
                modified_at=now,
            )
        )
        db.add(
            MedicalDocumentProfileRecord(
                id="profile-1",
                user_id="user-1",
                workspace_id="workspace-1",
                document_id="document-1",
                document_kind="research_paper",
                language="en",
                confidence=0.95,
            )
        )
        db.add(
            DocumentSectionRecord(
                id="section-1",
                user_id="user-1",
                workspace_id="workspace-1",
                document_id="document-1",
                section_type="results",
                original_title="Results",
                ordinal=1,
                page_start=2,
                page_end=2,
                char_start=0,
                char_end=28,
                text="The result was reported.",
                language="en",
            )
        )
        db.add(
            ParsedChunkRecord(
                id="chunk-1",
                user_id="user-1",
                workspace_id="workspace-1",
                document_id="document-1",
                chunk_index=0,
                chunk_type="medical_section",
                text="The result was reported.",
                metadata_json='{"section_type":"results","section_title":"Results","page_start":2,"page_end":2,"section_id":"section-1"}',
            )
        )
        db.commit()


@pytest.mark.parametrize("first_operation", ["create", "save"])
def test_postgres_create_and_save_use_the_same_lock_order(monkeypatch, first_operation):
    url = (
        os.getenv("GRAPHMIND_TEST_POSTGRES_URL")
        or os.getenv("TEST_POSTGRES_URL")
        or os.getenv("POSTGRES_TEST_DATABASE_URL")
    )
    if not url or not url.startswith("postgresql"):
        pytest.skip("set GRAPHMIND_TEST_POSTGRES_URL to test PostgreSQL row locks")

    schema = f"insight_locks_{uuid.uuid4().hex}"
    admin = create_engine(url)
    with admin.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    engine = create_engine(
        url,
        connect_args={"options": f"-csearch_path={schema} -clock_timeout=5000 -cstatement_timeout=10000"},
    )
    sessions = sessionmaker(bind=engine, autoflush=False)
    repository = AnalysisRepository(sessions, enabled=lambda: True)
    try:
        Base.metadata.create_all(engine)
        # Insert the parent first because this test uses real foreign keys.
        with sessions() as db:
            db.add(DocumentRecord(
                id="document-1", user_id="user-1", workspace_id="workspace-1",
                filename="paper.pdf", stored_filename="paper.pdf",
                original_filename="paper.pdf", file_hash="a" * 64,
                file_path="/tmp/paper.pdf",
                parsed_source_hash="b" * 64,
            ))
            db.commit()
        arguments = dict(
            document_id="document-1", user_id="user-1", workspace_id="workspace-1",
            source_hash="a" * 64, requested_by="user-1", provider="extractive",
            model_name="extractive-v1", prompt_version="medical-insights-v1",
            schema_version="medical-insights-v1",
        )
        run, _ = repository.create_or_reuse(**arguments)
        claimed = repository.mark_running(run["run_id"])
        output = MedicalInsightAnalyzer(provider=ExtractiveMedicalAIProvider()).run(
            [{"id": "chunk-1", "text": "The result was reported.",
              "metadata": {"section_type": "results", "page_start": 2}}],
            title="paper.pdf", document_kind="research_paper", language="en",
        )
        first_locked = threading.Event()
        second_attempting = threading.Event()
        operation = threading.local()
        connections = {}
        original_document = repository._document

        def coordinated_document(db, *args, **kwargs):
            name = operation.name
            connections[name] = db.scalar(text("SELECT pg_backend_pid()"))
            if name != first_operation:
                second_attempting.set()
            document = original_document(db, *args, **kwargs)
            if name == first_operation:
                first_locked.set()
                assert second_attempting.wait(10), "second transaction never reached the document lock"
            return document

        monkeypatch.setattr(repository, "_document", coordinated_document)

        def execute(name):
            operation.name = name
            if name == "create":
                return repository.create_or_reuse(**arguments)
            return repository.save_success(
                run["run_id"], output, attempt_count=claimed["attempt_count"]
            )

        # Hold one document lock until the other connection asks for it.
        # With run -> document in save_success, the create-first case deadlocks.
        second_operation = "save" if first_operation == "create" else "create"
        with ThreadPoolExecutor(max_workers=2) as workers:
            first = workers.submit(execute, first_operation)
            assert first_locked.wait(10), "first transaction never acquired the document lock"
            second = workers.submit(execute, second_operation)
            results = {
                first_operation: first.result(timeout=20),
                second_operation: second.result(timeout=20),
            }
        assert connections["create"] != connections["save"]
        reused, created = results["create"]
        assert not created
        assert reused["run_id"] == run["run_id"]
        assert results["save"]["status"] == "succeeded"
        assert results["save"]["evidence"]
        with sessions() as db:
            runs = db.scalars(select(MedicalAnalysisRunRecord)).all()
            assert len(runs) == 1
            assert runs[0].status == "succeeded"
            assert runs[0].is_current
            assert runs[0].attempt_count == claimed["attempt_count"]
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        admin.dispose()


def test_repository_persists_citations_and_filters_stale_source_versions():
    engine, sessions, repository = _repository()
    try:
        _paper_rows(sessions)
        run, created = repository.create_or_reuse(
            document_id="document-1",
            user_id="user-1",
            workspace_id="workspace-1",
            source_hash="a" * 64,
            requested_by="user-1",
            provider="extractive",
            model_name="extractive-v1",
            prompt_version="medical-insights-v1",
            schema_version="medical-insights-v1",
        )
        assert created
        claimed = repository.mark_running(run["run_id"])
        assert claimed["status"] == "running"

        output = MedicalInsightAnalyzer(provider=ExtractiveMedicalAIProvider()).run(
            [{"id": "chunk-1", "text": "The result was reported.", "metadata": {"section_type": "results", "section_title": "Results", "page_start": 2, "page_end": 2, "section_id": "section-1"}}],
            sections=[{"id": "section-1", "section_type": "results", "original_title": "Results", "page_start": 2, "page_end": 2}],
            title="paper.pdf",
            document_kind="research_paper",
            language="en",
        )
        saved = repository.save_success(run["run_id"], output)
        assert saved["status"] == "succeeded"
        assert saved["evidence"][0]["section_type"] == "results"
        assert saved["evidence"][0]["section_title"] == "Results"

        reused, created = repository.create_or_reuse(
            document_id="document-1",
            user_id="user-1",
            workspace_id="workspace-1",
            source_hash="a" * 64,
            requested_by="user-1",
            provider="extractive",
            model_name="extractive-v1",
            prompt_version="medical-insights-v1",
            schema_version="medical-insights-v1",
        )
        assert not created
        assert reused["status"] == "succeeded"
        assert "report" in reused
        assert reused["evidence"]

        with sessions() as db:
            document = db.get(DocumentRecord, "document-1")
            document.file_hash = "b" * 64
            db.commit()

        assert repository.get_latest("document-1", "user-1", "workspace-1") is None
        stale = repository.get_run(run["run_id"], "user-1", "workspace-1")
        assert stale["outdated"] is True
        assert stale["is_current"] is False

        with sessions() as db:
            assert db.get(MedicalAnalysisRunRecord, run["run_id"]).is_current is False

        with sessions() as db:
            assert len(db.scalars(select(MedicalAnalysisRunRecord)).all()) == 1
            assert len(db.scalars(select(MedicalAnalysisEvidenceRecord)).all()) >= 1
    finally:
        engine.dispose()


def test_repository_versions_and_returns_external_provider_parameters():
    engine, sessions, repository = _repository()
    try:
        _paper_rows(sessions)
        common = {
            "document_id": "document-1",
            "user_id": "user-1",
            "workspace_id": "workspace-1",
            "source_hash": "a" * 64,
            "requested_by": "user-1",
            "provider": "openai",
            "model_name": "test-model",
            "prompt_version": "medical-insights-v2",
            "schema_version": "medical-insights-v2",
            "max_input_tokens": 8000,
            "timeout_seconds": 45,
            "max_output_tokens": 3000,
            "provider_retry_count": 1,
        }

        first, created = repository.create_or_reuse(**common)

        assert created
        assert first["timeout_seconds"] == 45
        assert first["max_output_tokens"] == 3000
        assert first["provider_retry_count"] == 1

        changed, created = repository.create_or_reuse(
            **{**common, "max_output_tokens": 3500}
        )

        assert created
        assert changed["run_id"] != first["run_id"]
        assert changed["max_output_tokens"] == 3500
    finally:
        engine.dispose()


def test_repository_invalidates_report_when_parsed_chunks_change():
    engine, sessions, repository = _repository()
    try:
        _paper_rows(sessions)
        run, created = repository.create_or_reuse(
            document_id="document-1",
            user_id="user-1",
            workspace_id="workspace-1",
            source_hash="a" * 64,
            requested_by="user-1",
            provider="extractive",
            model_name="extractive-v1",
            prompt_version="medical-insights-v1",
            schema_version="medical-insights-v1",
        )
        assert created
        claimed = repository.mark_running(run["run_id"])
        assert claimed and claimed["attempt_count"] == 1
        output = MedicalInsightAnalyzer(provider=ExtractiveMedicalAIProvider()).run(
            [
                {
                    "id": "chunk-1",
                    "text": "The result was reported.",
                    "metadata": {
                        "section_type": "results",
                        "section_title": "Results",
                        "page_start": 2,
                        "page_end": 2,
                        "section_id": "section-1",
                    },
                }
            ],
            sections=[
                {
                    "id": "section-1",
                    "section_type": "results",
                    "original_title": "Results",
                    "page_start": 2,
                    "page_end": 2,
                }
            ],
            title="paper.pdf",
            document_kind="research_paper",
            language="en",
        )
        repository.save_success(
            run["run_id"], output, attempt_count=claimed["attempt_count"]
        )

        with sessions() as db:
            chunk = db.get(ParsedChunkRecord, "chunk-1")
            chunk.text = "The updated result was reported."
            db.commit()

        repository.refresh_parsed_source_hash(
            "document-1", "user-1", "workspace-1"
        )

        assert repository.get_latest("document-1", "user-1", "workspace-1") is None
        current = repository.get_run(run["run_id"], "user-1", "workspace-1")
        assert current["outdated"] is True
        assert current["is_current"] is False
    finally:
        engine.dispose()


def test_current_returns_the_newest_failed_reanalysis():
    engine, sessions, repository = _repository()
    try:
        _paper_rows(sessions)
        first, created = repository.create_or_reuse(
            document_id="document-1",
            user_id="user-1",
            workspace_id="workspace-1",
            source_hash="a" * 64,
            requested_by="user-1",
            provider="extractive",
            model_name="extractive-v1",
            prompt_version="medical-insights-v1",
            schema_version="medical-insights-v1",
        )
        assert created
        repository.mark_running(first["run_id"])
        output = MedicalInsightAnalyzer(provider=ExtractiveMedicalAIProvider()).run(
            [{"id": "chunk-1", "text": "The result was reported.", "metadata": {"section_type": "results"}}],
            title="paper.pdf",
            document_kind="research_paper",
            language="en",
        )
        repository.save_success(first["run_id"], output)

        second, created = repository.create_or_reuse(
            document_id="document-1",
            user_id="user-1",
            workspace_id="workspace-1",
            source_hash="a" * 64,
            requested_by="user-1",
            provider="extractive",
            model_name="extractive-v1",
            prompt_version="medical-insights-v1",
            schema_version="medical-insights-v1",
            force=True,
        )
        assert created
        repository.save_failure(second["run_id"], "provider_failed", "provider failed")

        current = repository.get_current("document-1", "user-1", "workspace-1")
        assert current["run_id"] == second["run_id"]
        assert current["status"] == "failed"
    finally:
        engine.dispose()


def test_status_reads_document_snapshot_instead_of_rehashing_source(monkeypatch):
    engine, sessions, repository = _repository()
    try:
        _paper_rows(sessions)
        run, created = repository.create_or_reuse(
            document_id="document-1",
            user_id="user-1",
            workspace_id="workspace-1",
            source_hash="a" * 64,
            requested_by="user-1",
            provider="extractive",
            model_name="extractive-v1",
            prompt_version="medical-insights-v1",
            schema_version="medical-insights-v1",
        )
        assert created

        import app.services.medical.ai.analysis_repository as repository_module

        def fail_if_rehashed(*_args, **_kwargs):
            raise AssertionError("status polling should use the stored snapshot")

        monkeypatch.setattr(repository_module, "_source_snapshot_hash", fail_if_rehashed)
        assert repository.get_current("document-1", "user-1", "workspace-1")["status"] == "queued"
        assert repository.get_run(run["run_id"], "user-1", "workspace-1")["status"] == "queued"
    finally:
        engine.dispose()


def test_create_reuses_stored_document_snapshot_without_rehashing_source(monkeypatch):
    engine, sessions, repository = _repository()
    try:
        _paper_rows(sessions)
        stored_snapshot = "c" * 64
        with sessions() as db:
            document = db.get(DocumentRecord, "document-1")
            document.parsed_source_hash = stored_snapshot
            db.commit()

        import app.services.medical.ai.analysis_repository as repository_module

        def fail_if_rehashed(*_args, **_kwargs):
            raise AssertionError("analysis creation should use the stored snapshot")

        monkeypatch.setattr(repository_module, "_source_snapshot_hash", fail_if_rehashed)
        run, created = repository.create_or_reuse(
            document_id="document-1",
            user_id="user-1",
            workspace_id="workspace-1",
            source_hash="a" * 64,
            requested_by="user-1",
            provider="extractive",
            model_name="extractive-v1",
            prompt_version="medical-insights-v1",
            schema_version="medical-insights-v1",
        )

        assert created
        assert run["parsed_source_hash"] == stored_snapshot
    finally:
        engine.dispose()


def test_repository_exposes_expired_run_as_failed_and_allows_retry():
    engine, sessions, repository = _repository()
    try:
        _paper_rows(sessions)
        run, created = repository.create_or_reuse(
            document_id="document-1",
            user_id="user-1",
            workspace_id="workspace-1",
            source_hash="a" * 64,
            requested_by="user-1",
            provider="extractive",
            model_name="extractive-v1",
            prompt_version="medical-insights-v1",
            schema_version="medical-insights-v1",
        )
        assert created

        with sessions() as db:
            row = db.get(MedicalAnalysisRunRecord, run["run_id"])
            row.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            db.commit()

        stalled = repository.get_current("document-1", "user-1", "workspace-1")
        assert stalled["status"] == "failed"
        assert stalled["error_code"] == "analysis_stalled"

        retried, created = repository.create_or_reuse(
            document_id="document-1",
            user_id="user-1",
            workspace_id="workspace-1",
            source_hash="a" * 64,
            requested_by="user-1",
            provider="extractive",
            model_name="extractive-v1",
            prompt_version="medical-insights-v1",
            schema_version="medical-insights-v1",
        )
        assert created
        assert retried["run_id"] == run["run_id"]
        assert retried["status"] == "queued"
    finally:
        engine.dispose()


def test_repository_hides_expired_run_when_document_was_deleted():
    engine, sessions, repository = _repository()
    try:
        _paper_rows(sessions)
        run, created = repository.create_or_reuse(
            document_id="document-1",
            user_id="user-1",
            workspace_id="workspace-1",
            source_hash="a" * 64,
            requested_by="user-1",
            provider="extractive",
            model_name="extractive-v1",
            prompt_version="medical-insights-v1",
            schema_version="medical-insights-v1",
        )
        assert created

        with sessions() as db:
            row = db.get(MedicalAnalysisRunRecord, run["run_id"])
            row.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            document = db.get(DocumentRecord, "document-1")
            document.deleted_at = datetime.now(timezone.utc)
            db.commit()

        assert repository.get_run(run["run_id"], "user-1", "workspace-1") is None
        assert repository.get_current("document-1", "user-1", "workspace-1") is None
    finally:
        engine.dispose()
