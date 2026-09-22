"""End-to-end PDF parsing and persisted medical insight regression coverage."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.endpoints import medical_insights
from app.api.endpoints import documents_with_markdown
from app.core.database import Base
from app.core.errors import AppError
from app.core.config import settings
from app.models.persistence import DocumentRecord
from app.services.document_parser import PDF_TEXT_PARSER_VERSION
from app.services.medical.ai.analysis_repository import AnalysisRepository
from app.services.medical.ai.provider import ExtractiveMedicalAIProvider
from app.services.parsed_artifact_repository import ParsedArtifactRepository
from app.tasks import medical_analysis


USER_ID = "readability-test-user"
WORKSPACE_ID = "readability-test-workspace"
DOCUMENT_ID = "readability-test-document"
MODEL_NAME = "extractive-v2"


def _write_text_pdf(path: Path, lines: list[str]) -> None:
    """Write a small standards-compliant, text-selectable PDF without fixtures."""
    commands = []
    for index, line in enumerate(lines):
        escaped = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        commands.append(f"BT /F1 10 Tf 48 {748 - index * 19} Td ({escaped}) Tj ET")
    stream = ("\n".join(commands) + "\n").encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>"
        ),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n"
        + stream
        + b"endstream",
    ]
    pdf = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, body in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf.extend(f"{index} 0 obj\n".encode("ascii"))
        pdf.extend(body)
        pdf.extend(b"\nendobj\n")
    xref_offset = len(pdf)
    pdf.extend(f"xref\n0 {len(offsets)}\n".encode("ascii"))
    pdf.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        pdf.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    pdf.extend(
        f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n".encode("ascii")
    )
    path.write_bytes(pdf)


def _make_old_analysis(repository: AnalysisRepository, prompt_version: str) -> dict:
    source = repository.get_source(DOCUMENT_ID, USER_ID, WORKSPACE_ID)
    assert source is not None
    run, created = repository.create_or_reuse(
        document_id=DOCUMENT_ID,
        user_id=USER_ID,
        workspace_id=WORKSPACE_ID,
        source_hash=source["source_hash"],
        parsed_source_hash=source["parsed_source_hash"],
        requested_by=USER_ID,
        provider="extractive",
        model_name=MODEL_NAME,
        prompt_version=prompt_version,
        schema_version=settings.MEDICAL_AI_SCHEMA_VERSION,
        redact_pii=True,
    )
    assert created
    return run


def test_pdf_reparse_and_reopen_only_returns_new_readable_analysis(tmp_path, monkeypatch):
    from sqlalchemy.pool import StaticPool

    pdf_path = tmp_path / "fabry-cohort.pdf"
    _write_text_pdf(
        pdf_path,
        [
            "Fabry disease biomarker study",
            "Authors: Author One, Author Two",
            "Abstract",
            "Objectives: We assessed biomarkers in adults with Fabry disease.",
            "Methods: We enrolled 72 adults with Fabry disease and 38 matched controls.",
            "Results: Plasma globotriaosylceramide levels were higher in participants with Fabry disease.",
            "Conclusion: The measured biomarker differed between groups.",
            "Introduction",
            "Fabry disease is a rare inherited lysosomal disorder.",
            "Methods",
            "Participants: The study included 72 adults with confirmed Fabry disease and 38 matched controls.",
            "Results",
            "Serum Gb3 was higher among adults with Fabry disease than controls.",
            "ary Gb3 levels were higher in the cohort.",
            "Discussion",
            "The findings describe a selected adult cohort and require further study.",
            "orm, glo- Introduction artifacts should not become findings.",
            "References",
            "1. Example study reference.",
        ],
    )

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, future=True)
    with session_factory() as db:
        db.add(
            DocumentRecord(
                id=DOCUMENT_ID,
                user_id=USER_ID,
                workspace_id=WORKSPACE_ID,
                filename="stored-fabry.pdf",
                stored_filename="stored-fabry.pdf",
                original_filename=pdf_path.name,
                file_extension=".pdf",
                file_type="pdf",
                mime_type="application/pdf",
                file_hash="a" * 64,
                file_path=str(pdf_path),
                file_size=pdf_path.stat().st_size,
                status="parsed",
                parser_version=PDF_TEXT_PARSER_VERSION,
            )
        )
        db.commit()

    repository = AnalysisRepository(session_factory, enabled=lambda: True)
    artifact_repository = ParsedArtifactRepository(
        session_factory, enabled=lambda: True
    )
    monkeypatch.setattr(
        documents_with_markdown, "parsed_artifact_repository", artifact_repository
    )
    monkeypatch.setattr(
        documents_with_markdown.entity_extractor,
        "extract_from_parsed_document",
        lambda _parsed: [],
    )
    parsed = documents_with_markdown.parse_document_file(
        filename="stored-fabry.pdf",
        file_path=str(pdf_path),
        original_filename=pdf_path.name,
        user_id=USER_ID,
        document_id=DOCUMENT_ID,
        workspace_id=WORKSPACE_ID,
    )
    assert parsed["metadata"]["persistence_status"] == "persisted"
    assert parsed["medical_analysis"]["document_kind"] == "research_paper"

    source = repository.get_source(DOCUMENT_ID, USER_ID, WORKSPACE_ID)
    assert source is not None
    assert {section["section_type"] for section in source["sections"]} >= {
        "methods",
        "results",
        "scope",
    }
    assert source["chunks"]

    monkeypatch.setattr(settings, "MEDICAL_AI_PROVIDER", "extractive")
    monkeypatch.setattr(settings, "MEDICAL_AI_MODEL", MODEL_NAME)
    monkeypatch.setattr(medical_insights, "medical_analysis_repository", repository)
    monkeypatch.setattr(medical_insights, "_require_repository", lambda: None)
    monkeypatch.setattr(
        medical_insights, "resolve_workspace_id", lambda *_args: WORKSPACE_ID
    )

    def scoped_document(document_id, user_id, workspace_id):
        assert (document_id, user_id, workspace_id) == (
            DOCUMENT_ID,
            USER_ID,
            WORKSPACE_ID,
        )
        with session_factory() as db:
            document = db.get(DocumentRecord, document_id)
            return {
                "document_id": document.id,
                "filename": document.filename,
                "file_path": document.file_path,
                "original_filename": document.original_filename,
                "file_extension": document.file_extension,
                "file_hash": document.file_hash,
                "parser_version": document.parser_version,
            }

    monkeypatch.setattr(medical_insights, "_get_scoped_document", scoped_document)

    # Simulate a report created before semantic extraction changes were versioned.
    old_run = _make_old_analysis(repository, "medical-insights-v3")
    monkeypatch.setattr(
        medical_analysis,
        "medical_analysis_repository",
        repository,
    )
    monkeypatch.setattr(
        medical_analysis,
        "get_provider",
        lambda _name, model_name, **_kwargs: ExtractiveMedicalAIProvider(model_name),
    )
    old_result = medical_analysis.run_medical_analysis_once(old_run["run_id"])
    assert old_result["status"] == "succeeded"

    with pytest.raises(AppError) as old_pipeline_error:
        asyncio.run(
            medical_insights.get_current_medical_insights(
                DOCUMENT_ID,
                workspace_id=WORKSPACE_ID,
                user=SimpleNamespace(id=USER_ID),
            )
        )
    assert old_pipeline_error.value.code == "analysis_outdated"
    assert old_pipeline_error.value.details["reason"] == "analysis_pipeline_changed"

    # A deployment with an old persisted parser marker must reparse the actual PDF
    # and return an outdated response before exposing any saved report.
    with session_factory() as db:
        document = db.get(DocumentRecord, DOCUMENT_ID)
        document.parser_version = "document-parser-pdf-readable-v1"
        db.commit()

    with pytest.raises(AppError) as old_parser_error:
        asyncio.run(
            medical_insights.get_current_medical_insights(
                DOCUMENT_ID,
                workspace_id=WORKSPACE_ID,
                user=SimpleNamespace(id=USER_ID),
            )
        )
    assert old_parser_error.value.code == "analysis_outdated"
    assert old_parser_error.value.details["reason"] == "parser_version_changed"
    with session_factory() as db:
        assert db.get(DocumentRecord, DOCUMENT_ID).parser_version == PDF_TEXT_PARSER_VERSION

    fresh_source = repository.get_source(DOCUMENT_ID, USER_ID, WORKSPACE_ID)
    assert fresh_source is not None
    new_run, created = repository.create_or_reuse(
        document_id=DOCUMENT_ID,
        user_id=USER_ID,
        workspace_id=WORKSPACE_ID,
        source_hash=fresh_source["source_hash"],
        parsed_source_hash=fresh_source["parsed_source_hash"],
        requested_by=USER_ID,
        provider="extractive",
        model_name=MODEL_NAME,
        prompt_version=medical_insights._effective_prompt_version(),
        schema_version=settings.MEDICAL_AI_SCHEMA_VERSION,
        redact_pii=True,
    )
    assert created
    assert new_run["run_id"] != old_run["run_id"]
    result = medical_analysis.run_medical_analysis_once(new_run["run_id"])
    assert result["status"] == "succeeded"

    reopened = asyncio.run(
        medical_insights.get_current_medical_insights(
            DOCUMENT_ID,
            workspace_id=WORKSPACE_ID,
            user=SimpleNamespace(id=USER_ID),
        )
    )
    assert reopened["run_id"] == new_run["run_id"]
    assert reopened["parser_version"] == PDF_TEXT_PARSER_VERSION
    assert reopened["prompt_version"] == medical_insights._effective_prompt_version()

    report = reopened["report"]
    findings = [finding["statement"] for finding in report["key_findings"]]
    assert findings
    assert all(not text.startswith("Objectives") for text in findings)
    assert all("ary Gb3" not in text for text in findings)
    assert all("orm, glo- Introduction" not in text for text in findings)
    population = report["study_methods"]["population"]["value"]
    assert "72 adults" in population
    assert "Author One" not in population
    assert "Author Two" not in population

    reopened_again = asyncio.run(
        medical_insights.get_current_medical_insights(
            DOCUMENT_ID,
            workspace_id=WORKSPACE_ID,
            user=SimpleNamespace(id=USER_ID),
        )
    )
    assert reopened_again["run_id"] == reopened["run_id"]

    engine.dispose()
