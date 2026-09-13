"""Tests for source-backed questions to discuss with a healthcare professional."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.services.medical.ai.analyzer import MedicalInsightAnalyzer
from app.services.medical.ai.citation_validator import evidence_rows, validate_citations
from app.services.medical.ai.context_builder import AnalysisContext, EvidenceItem
from app.services.medical.ai.exceptions import MedicalInsightValidationError
from app.services.medical.ai.models import MedicalInsightReport, QuestionSuggestion
from app.services.medical.ai.prompt_builder import build_prompt
from app.services.medical.ai.provider import ExtractiveMedicalAIProvider
from app.services.medical.ai.question_validator import validate_questions
from app.services.medical.ai.safety_validator import validate_safety
from app.services.medical.ai.support_validator import validate_support


def _context(*evidence: tuple[str, str, str]) -> AnalysisContext:
    items = [
        EvidenceItem(
            evidence_id=evidence_id,
            chunk_id=f"chunk-{index}",
            section_id=f"section-{index}",
            section_type=section_type,
            section_title=section_type.title(),
            page_start=index,
            page_end=index,
            character_start=index * 100,
            character_end=index * 100 + len(text),
            text=text,
            token_count=10,
            source_index=index,
        )
        for index, (evidence_id, section_type, text) in enumerate(evidence, start=1)
    ]
    return AnalysisContext(
        title="Example paper",
        document_kind="research_paper",
        language="en",
        evidence=items,
        total_chunks=len(items),
        max_input_tokens=200,
    )


def _report(*questions: dict) -> MedicalInsightReport:
    return MedicalInsightReport.model_validate(
        {
            "document_kind": "research_paper",
            "language": "en",
            "overview": {
                "title": "Example paper",
                "summary": "The paper reports a result.",
                "study_type": "Research paper",
                "evidence_ids": ["EVIDENCE_001"],
            },
            "key_findings": [
                {
                    "id": "finding_001",
                    "statement": "The paper reports a result.",
                    "plain_explanation": "This is what the paper says.",
                    "evidence_ids": ["EVIDENCE_001"],
                    "evidence_level": "reported_in_document",
                    "interpretation_type": "direct_statement",
                }
            ],
            "question_suggestions": list(questions),
            "questions_for_professional": [],
        }
    )


def _question(
    *,
    suggestion_id: str = "question_001",
    question: str = "Which people were included in this study?",
    evidence_ids: list[str] | None = None,
    rationale: str = "The study describes a population, so it is useful to discuss who the findings may apply to.",
    category: str = "applicability",
) -> dict:
    return {
        "id": suggestion_id,
        "question": question,
        "rationale": rationale,
        "category": category,
        "evidence_ids": evidence_ids or ["EVIDENCE_001"],
        "interpretation_type": "inference",
    }


def test_question_suggestion_has_bounded_structured_fields():
    item = QuestionSuggestion.model_validate(_question())

    assert item.category == "applicability"
    assert item.evidence_ids == ["EVIDENCE_001"]

    with pytest.raises(ValidationError):
        QuestionSuggestion.model_validate({**_question(), "evidence_ids": []})
    with pytest.raises(ValidationError):
        QuestionSuggestion.model_validate({**_question(), "category": "diagnosis"})
    with pytest.raises(ValidationError):
        QuestionSuggestion.model_validate({**_question(), "question": ""})
    with pytest.raises(ValidationError):
        QuestionSuggestion.model_validate({**_question(), "question": "Q" * 501})
    with pytest.raises(ValidationError):
        QuestionSuggestion.model_validate({**_question(), "rationale": ""})
    with pytest.raises(ValidationError):
        QuestionSuggestion.model_validate({**_question(), "interpretation_type": "claim"})


def test_report_rejects_more_than_five_questions_and_keeps_v2_compatibility():
    questions = [_question(suggestion_id=f"question_{index:03d}") for index in range(6)]
    with pytest.raises(ValidationError):
        _report(*questions)

    with pytest.raises(ValidationError):
        MedicalInsightReport.model_validate(
            {
                "schema_version": "medical-insights-v3",
                "document_kind": "research_paper",
                "language": "en",
                "overview": {
                    "title": "Example paper",
                    "summary": "A saved V3 report.",
                    "study_type": "Research paper",
                    "evidence_ids": ["EVIDENCE_001"],
                },
                "questions_for_professional": ["An uncited legacy question."],
            }
        )

    legacy = MedicalInsightReport.model_validate(
        {
            "document_kind": "research_paper",
            "language": "en",
            "overview": {
                "title": "Old report",
                "summary": "A saved V2 report.",
                "study_type": "Research paper",
                "evidence_ids": ["EVIDENCE_001"],
            },
            "key_findings": [],
            "questions_for_professional": ["What should I discuss with a professional?"],
        }
    )
    assert legacy.schema_version == "medical-insights-v2"
    assert legacy.question_suggestions == []


def test_question_validation_requires_useful_current_non_reference_evidence():
    context = _context(
        ("EVIDENCE_001", "population", "The study included adults with the condition."),
        ("EVIDENCE_002", "references", "A cited article about the condition."),
    )

    valid = validate_questions(_report(_question()), context)
    assert valid.valid, valid.errors

    vague = validate_questions(
        _report(_question(question="Is it useful?")),
        context,
    )
    assert not vague.valid
    assert any("too vague" in error for error in vague.errors)

    statement = validate_questions(
        _report(_question(question="This study is useful to understand.")),
        context,
    )
    assert not statement.valid
    assert any("not phrased as a question" in error for error in statement.errors)

    unknown = validate_questions(
        _report(_question(evidence_ids=["EVIDENCE_999"])),
        context,
    )
    assert not unknown.valid
    assert any("unknown evidence id" in error for error in unknown.errors)

    references = validate_questions(
        _report(_question(evidence_ids=["EVIDENCE_002"])),
        context,
    )
    assert not references.valid
    assert any("references section" in error for error in references.errors)


def test_question_validation_rejects_duplicate_questions_and_evidence_ids():
    context = _context(("EVIDENCE_001", "results", "The study reports a result."))
    report = _report(
        _question(),
        _question(
            suggestion_id="question_002",
            question="Which people were included in this study? ",
            evidence_ids=["EVIDENCE_001", "EVIDENCE_001"],
        ),
    )

    validation = validate_questions(report, context)

    assert not validation.valid
    assert any("duplicates another question" in error for error in validation.errors)
    assert any("duplicate evidence_ids" in error for error in validation.errors)

    duplicate_id = _report(
        _question(question="Which people were included in this study?"),
        _question(
            question="What limitation should I discuss with my doctor?",
            rationale="The study reports a limitation that may affect interpretation.",
        ),
    )
    duplicate_validation = validate_questions(duplicate_id, context)

    assert not duplicate_validation.valid
    assert any("duplicates another question id" in error for error in duplicate_validation.errors)


@pytest.mark.parametrize(
    "question",
    [
        "What does eGFR mean?",
        "What is migalastat?",
        "GLA 基因是什么意思？",
    ],
)
def test_question_validation_allows_specific_terms_without_generic_context(question):
    context = _context(("EVIDENCE_001", "results", "The source mentions eGFR, migalastat, and GLA."))

    validation = validate_questions(
        _report(_question(question=question, rationale="The cited passage contains this term.")),
        context,
    )

    assert validation.valid, validation.errors


def test_question_citations_support_and_safety_are_checked_like_other_report_content():
    context = _context(("EVIDENCE_001", "results", "The study included 42 patients."))
    report = _report(
        _question(
            question="Which patients were included in the study?",
            rationale="The study reports its patient population, so this is useful to discuss.",
        )
    )

    assert validate_citations(report, context).valid
    rows = evidence_rows(report, context)
    assert {row["finding_id"] for row in rows} == {"overview", "finding_001", "question:question_001"}
    assert validate_support(report, context).valid
    assert validate_safety(report).valid

    unsafe = _report(
        _question(
            question="Should I stop my medicine and change the dose?",
            rationale="The paper mentions medication, but it cannot instruct an individual patient.",
        )
    )
    assert not validate_safety(unsafe).valid


@pytest.mark.parametrize(
    "question",
    [
        "我是不是已经患有这种病？",
        "我应该停药吗？",
        "我应该开始服用这种药吗？",
        "我应该换成论文里的药吗？",
        "我每天应该服用多少毫克？",
        "这个结果是不是证明我得了癌症？",
        "我怎样才能马上使用这种实验药？",
        "既然研究有效，我是不是也一定会有效？",
        "Should I stop taking my medication?",
        "Should I start taking this medication?",
        "Should I increase my dosage?",
        "How much medication should I take?",
        "Does this prove that I have this disease?",
    ],
)
def test_question_safety_rejects_first_person_diagnosis_and_treatment_instructions(question):
    report = _report(_question(question=question))

    result = validate_safety(report)

    assert not result.valid


@pytest.mark.parametrize(
    "question",
    [
        "这项治疗目前处于什么研究阶段？",
        "这篇论文的结果是否已经在更大规模研究中验证？",
        "研究人群与我的情况是否具有可比性？",
        "Could these findings apply to people like me?",
    ],
)
def test_question_safety_allows_evidence_bound_discussion_questions(question):
    report = _report(_question(question=question))

    result = validate_safety(report)

    assert result.valid, result.errors


def test_extractive_provider_emits_cited_question_suggestions():
    context = _context(
        ("EVIDENCE_001", "population", "The study included adults with the condition."),
        ("EVIDENCE_002", "limitations", "The authors noted limited follow-up."),
        ("EVIDENCE_003", "results", "The study reported the primary outcome."),
    )

    output = MedicalInsightAnalyzer(provider=ExtractiveMedicalAIProvider()).run(
        [
            {
                "id": item.chunk_id,
                "text": item.text,
                "section_type": item.section_type,
                "section_title": item.section_title,
                "page_start": item.page_start,
                "page_end": item.page_end,
                "section_id": item.section_id,
            }
            for item in context.evidence
        ],
        title=context.title,
        document_kind=context.document_kind,
        language=context.language,
    )

    assert output.questions.valid, output.questions.errors
    assert output.report.schema_version == "medical-insights-v3"
    assert output.report.question_suggestions
    assert all(item.evidence_ids for item in output.report.question_suggestions)


def test_analyzer_repairs_a_question_with_invalid_evidence():
    invalid = _report(_question(evidence_ids=["EVIDENCE_UNKNOWN"])).model_dump()
    valid = _report(_question()).model_dump()
    provider = ExtractiveMedicalAIProvider()

    class RepairProvider(ExtractiveMedicalAIProvider):
        def __init__(self):
            self.calls = 0

        def generate(self, prompt, context):
            self.calls += 1
            return invalid if self.calls == 1 else valid

    repair_provider = RepairProvider()
    output = MedicalInsightAnalyzer(provider=repair_provider).run(
        [{"id": "chunk-1", "text": "The study reports a result.", "section_type": "results"}],
        title="Example paper",
        document_kind="research_paper",
        language="en",
    )

    assert repair_provider.calls == 2
    assert output.questions.valid


def test_analyzer_rejects_personalized_medication_question_after_repair():
    unsafe = _report(
        _question(
            question="Would switching to the drug in this paper be better for me?"
        )
    ).model_dump()

    class UnsafeProvider(ExtractiveMedicalAIProvider):
        def __init__(self):
            self.calls = 0

        def generate(self, prompt, context):
            self.calls += 1
            return unsafe

    provider = UnsafeProvider()
    with pytest.raises(MedicalInsightValidationError):
        MedicalInsightAnalyzer(provider=provider).run(
            [{"id": "chunk-1", "text": "The study reports a result.", "section_type": "results"}],
            title="Example paper",
            document_kind="research_paper",
            language="en",
        )

    assert provider.calls == 2


def test_v3_normalization_drops_legacy_questions_from_a_provider_payload():
    payload = _report().model_dump()
    payload["schema_version"] = "medical-insights-v2"
    payload["questions_for_professional"] = ["This legacy question has no evidence IDs."]

    class LegacyProvider(ExtractiveMedicalAIProvider):
        def generate(self, prompt, context):
            return payload

    output = MedicalInsightAnalyzer(provider=LegacyProvider()).run(
        [{"id": "chunk-1", "text": "The study reports a result.", "section_type": "results"}],
        title="Example paper",
        document_kind="research_paper",
        language="en",
    )

    assert output.report.schema_version == "medical-insights-v3"
    assert output.report.questions_for_professional == []


def test_prompt_describes_structured_questions():
    prompt = build_prompt(_context(("EVIDENCE_001", "results", "The study reports a result.")))

    assert "question_suggestions" in prompt
    assert "healthcare professional" in prompt
    assert "questions_for_professional" in prompt
