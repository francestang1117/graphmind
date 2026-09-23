"""Tests for source-backed questions to discuss with a healthcare professional."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.services.medical.ai.analyzer import MedicalInsightAnalyzer
from app.services.medical.ai.citation_validator import evidence_rows, validate_citations
from app.services.medical.ai.context_builder import AnalysisContext, EvidenceItem
from app.services.medical.ai.models import MedicalInsightReport, QuestionSuggestion
from app.services.medical.ai.prompt_builder import build_prompt
from app.services.medical.ai.provider import ExtractiveMedicalAIProvider
from app.services.medical.ai.question_validator import validate_questions
from app.services.medical.ai.question_templates import (
    QuestionTemplateError,
    _CATEGORY_TOPICS,
    _TEMPLATES,
    _TOPIC_SOURCES,
)
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


def _structured_question(
    *,
    suggestion_id: str = "question_001",
    topic: str = "study_population",
    source_kind: str = "study_methods",
    source_id: str = "population",
    **overrides,
) -> dict:
    question = _question(suggestion_id=suggestion_id, **overrides)
    question.update(
        {
            "topic": topic,
            "source_kind": source_kind,
            "source_id": source_id,
            "evidence_ids": [],
        }
    )
    return question


def _structured_report(question: dict) -> MedicalInsightReport:
    payload = _report(question).model_dump()
    payload["study_methods"] = {
        "population": {
            "value": "The study included adults with the condition.",
            "support_status": "supported",
            "evidence_ids": ["EVIDENCE_001"],
        }
    }
    return MedicalInsightReport.model_validate(payload)


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

    draft_without_provider_evidence = QuestionSuggestion.model_validate(
        {**_question(), "evidence_ids": []}
    )
    assert draft_without_provider_evidence.evidence_ids == []
    with pytest.raises(ValidationError):
        QuestionSuggestion.model_validate({**_question(), "category": "diagnosis"})
    draft = QuestionSuggestion.model_validate(
        {**_question(), "question": "", "rationale": ""}
    )
    assert draft.question == ""
    assert draft.rationale == ""
    with pytest.raises(ValidationError):
        QuestionSuggestion.model_validate({**_question(), "question": "Q" * 501})
    with pytest.raises(ValidationError):
        QuestionSuggestion.model_validate({**_question(), "interpretation_type": "claim"})
    with pytest.raises(ValidationError):
        QuestionSuggestion.model_validate({**_question(), "topic": "personal_treatment"})
    with pytest.raises(ValidationError):
        QuestionSuggestion.model_validate({**_question(), "topic": "evidence_gap"})
    with pytest.raises(ValidationError):
        QuestionSuggestion.model_validate({**_question(), "category": "evidence_gap"})


def test_every_advertised_question_topic_has_a_resolvable_source():
    advertised_topics = {
        topic for topics in _CATEGORY_TOPICS.values() for topic in topics
    }

    assert advertised_topics
    assert advertised_topics <= set(_TOPIC_SOURCES)
    assert all(advertised_topics <= set(templates) for templates in _TEMPLATES.values())


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
        "Could these findings help people like me?",
        "What treatment outcomes did the study report for people with my condition?",
        "Are these findings appropriate for my condition?",
        "Is this study suitable for my situation?",
        "Could this study help me?",
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
    assert all(item.source_kind and item.source_id for item in output.report.question_suggestions)
    assert "extractive_output" in output.report.warnings
    assert output.report.what_it_means == []
    assert output.report.what_it_does_not_mean == []


def test_extractive_provider_does_not_invent_population_from_results_text():
    context = _context(
        ("EVIDENCE_001", "results", "The study reported an outcome in 42 participants."),
    )

    output = ExtractiveMedicalAIProvider().generate("prompt", context)

    assert output["study_methods"]["population"] == {}
    assert output["question_suggestions"] == []


def test_extractive_provider_rejects_author_names_as_population_evidence():
    context = _context(
        (
            "EVIDENCE_001",
            "population",
            "Tomoko Shiga, Takahiro Tsukimura, Takao Kubota, and Tadayasu Togawa. "
            "Plasma analysis included 15 classic Fabry men, 6 late-onset men, "
            "11 women, and 36 controls.",
        )
    )

    output = ExtractiveMedicalAIProvider().generate("prompt", context)

    population = output["study_methods"]["population"]
    assert population["support_status"] == "supported"
    assert "Tomoko Shiga" not in population["value"]
    assert "15 classic Fabry men" in population["value"]
    assert "36 controls" in population["value"]


def test_extractive_provider_does_not_turn_objectives_into_findings():
    context = _context(
        ("EVIDENCE_001", "abstract", "Objectives The study assessed a biomarker."),
        ("EVIDENCE_003", "results", "Objective: To assess biomarkers in the cohort."),
        ("EVIDENCE_002", "results", "Results Fabry patients had higher biomarker levels."),
    )

    output = ExtractiveMedicalAIProvider().generate("prompt", context)

    statements = [item["statement"] for item in output["key_findings"]]
    assert all("Objectives" not in statement for statement in statements)
    assert statements == ["Results Fabry patients had higher biomarker levels."]


def test_extractive_provider_skips_fragmented_source_text():
    context = _context(
        ("EVIDENCE_001", "results", "ary Gb3 isoforms were higher in patients..."),
        ("EVIDENCE_002", "results", "The measured isoforms were higher in patients."),
    )

    output = ExtractiveMedicalAIProvider().generate("prompt", context)

    assert [item["statement"] for item in output["key_findings"]] == [
        "The measured isoforms were higher in patients."
    ]


def test_extractive_provider_does_not_mark_a_damaged_method_passage_supported():
    context = _context(
        (
            "EVIDENCE_001",
            "methods",
            "The clinical signifi- classified into three clinical types.",
        )
    )

    methods = ExtractiveMedicalAIProvider().generate("prompt", context)["study_methods"]

    assert methods["comparator"] == {}
    assert methods["human_animal_in_vitro"] == {}


def test_extractive_provider_marks_background_when_no_study_aim_is_found():
    context = _context(
        (
            "EVIDENCE_001",
            "abstract",
            "Fabry disease is characterized by systemic accumulation of biomarkers.",
        )
    )

    output = ExtractiveMedicalAIProvider().generate("prompt", context)

    assert "study_aim_unavailable" in output["warnings"]


def test_extractive_provider_uses_field_matching_sentences_for_method_attributes():
    context = _context(
        (
            "EVIDENCE_001",
            "methods",
            "This trial included 200 adults. The comparison group received placebo.",
        )
    )

    methods = ExtractiveMedicalAIProvider().generate("prompt", context)["study_methods"]

    assert methods["sample_size"]["support_status"] == "supported"
    assert methods["sample_size"]["value"] == "This trial included 200 adults."
    assert methods["comparator"]["support_status"] == "supported"
    assert methods["comparator"]["value"] == "The comparison group received placebo."

    no_sample_size = ExtractiveMedicalAIProvider().generate(
        "prompt",
        _context(("EVIDENCE_002", "methods", "Patients were monitored during follow-up.")),
    )["study_methods"]
    assert no_sample_size["sample_size"] == {}


@pytest.mark.parametrize("population_text", ["患者共1040例参与研究。", "研究人群包括儿童患者。"])
def test_extractive_provider_detects_contiguous_chinese_population_terms(population_text):
    context = _context(("EVIDENCE_001", "population", population_text))

    output = ExtractiveMedicalAIProvider().generate("prompt", context)

    population = output["study_methods"]["population"]
    assert population["support_status"] == "supported"
    assert population["value"] == population_text
    assert output["question_suggestions"][0]["topic"] == "study_population"


@pytest.mark.parametrize(
    ("measurement_text", "expected_value"),
    [
        ("A total of 200 patients were enrolled.", False),
        ("The experiment was performed in rats.", False),
        ("本研究纳入1040名患者。", False),
        ("该实验使用小鼠模型。", False),
        ("检测肿瘤组织中的蛋白表达。", True),
        ("使用组织切片进行病理分析。", True),
        ("研究人员使用统计模型分析数据。", False),
        ("本研究采用人工智能方法处理影像。", False),
        ("由两人独立审查研究质量。", False),
        ("该研究由医院组织开展。", False),
        ("研究团队组织实施随访。", False),
        (
            "Plasma Lyso-Gb3 and urinary Gb3 isoforms were measured using LC-MS/MS.",
            True,
        ),
        (
            "The diagnosis was performed using an assay, with patients classified into three types.",
            False,
        ),
    ],
)
def test_extractive_provider_requires_a_measured_object_for_what_was_measured(
    measurement_text, expected_value
):
    output = ExtractiveMedicalAIProvider().generate(
        "prompt", _context(("EVIDENCE_001", "methods", measurement_text))
    )

    attribute = output["study_methods"]["human_animal_in_vitro"]
    assert bool(attribute) is expected_value
    if expected_value:
        assert attribute["value"] == measurement_text


def test_extractive_provider_keeps_method_fields_out_of_results_and_compacts_comparator():
    context = _context(
        (
            "EVIDENCE_001",
            "methods",
            "Plasma analysis included 15 classic Fabry men and 36 control subjects. "
            "Urine analysis included 5 classic Fabry men and 11 control subjects. "
            "Plasma Lyso-Gb3 and urinary Gb3 isoforms were measured using LC-MS/MS. "
            "The diagnosis was performed using an assay, with patients classified into three types.",
        ),
        (
            "EVIDENCE_002",
            "results",
            "The mean plasma Lyso-Gb3 values were reported with the figure caption.",
        ),
    )

    methods = ExtractiveMedicalAIProvider().generate("prompt", context)["study_methods"]

    assert "15 classic Fabry men" in methods["sample_size"]["value"]
    assert "5 classic Fabry men" in methods["sample_size"]["value"]
    assert "mean plasma" not in methods["sample_size"]["value"]
    assert methods["comparator"]["value"] == "Plasma: 36 control subjects; Urine: 11 control subjects"
    assert methods["human_animal_in_vitro"]["value"] == (
        "Plasma Lyso-Gb3 and urinary Gb3 isoforms were measured using LC-MS/MS."
    )


def test_extractive_provider_splits_mixed_plasma_and_urine_cohorts():
    context = _context(
        (
            "EVIDENCE_001",
            "methods",
            "Plasma Lyso-Gb3 and related analogs were measured in 15 classic Fabry men, "
            "6 later-onset Fabry men, 11 Fabry women, and 36 controls, while urinary "
            "Gb3 isoforms were measured in 5 classic Fabry men, 5 later-onset Fabry men, "
            "17 Fabry women, and 11 controls, using LC-MS/MS.",
        ),
        ("EVIDENCE_002", "results", "The results 1533"),
    )

    report = ExtractiveMedicalAIProvider().generate("prompt", context)
    methods = report["study_methods"]

    assert methods["sample_size"]["value"] == (
        "Plasma: 15 classic Fabry men; 6 later-onset Fabry men; 11 Fabry women; "
        "36 controls; Urine: 5 classic Fabry men; 5 later-onset Fabry men; "
        "17 Fabry women; 11 controls"
    )
    assert methods["comparator"]["value"] == "Plasma: 36 controls; Urine: 11 controls"
    assert all("1533" not in finding["statement"] for finding in report["key_findings"])


def test_analyzer_deduplicates_multiple_sources_for_same_topic():
    first = _structured_question(
        category="clarify_finding",
        topic="reported_result",
        source_kind="key_findings",
        source_id="finding_001",
    )
    second = _structured_question(
        suggestion_id="question_002",
        category="clarify_finding",
        topic="reported_result",
        source_kind="key_findings",
        source_id="finding_002",
    )
    payload = _structured_report(first).model_dump()
    payload["question_suggestions"] = [first, second]
    payload["key_findings"].append(
        {
            "id": "finding_002",
            "statement": "The paper reports another result.",
            "plain_explanation": "This is another reported finding.",
            "evidence_ids": ["EVIDENCE_002"],
            "evidence_level": "reported_in_document",
            "interpretation_type": "direct_statement",
        }
    )

    class Provider(ExtractiveMedicalAIProvider):
        def __init__(self):
            self.calls = 0

        def generate(self, prompt, context):
            self.calls += 1
            return payload

    provider = Provider()
    output = MedicalInsightAnalyzer(provider=provider).run(
        [
            {"id": "chunk-1", "text": "The study reported result one.", "section_type": "results"},
            {"id": "chunk-2", "text": "The study reported result two.", "section_type": "results"},
        ],
        title="Example paper",
        document_kind="research_paper",
        language="en",
    )

    assert provider.calls == 1
    assert len(output.report.question_suggestions) == 1
    assert output.report.question_suggestions[0].source_id == "finding_001"


def test_question_source_binding_rejects_an_existing_but_unrelated_evidence_id():
    report = _structured_report(
        _structured_question(
            topic="study_population",
            source_kind="study_methods",
            source_id="population",
        )
    )
    context = _context(
        ("EVIDENCE_001", "results", "The study reported a result."),
    )

    validation = validate_questions(report, context)

    assert not validation.valid
    assert any("population" in error for error in validation.errors)


def test_question_source_binding_resolves_report_object_evidence():
    report = _structured_report(
        _structured_question(
            topic="study_population",
            source_kind="study_methods",
            source_id="population",
        )
    )
    context = _context(
        ("EVIDENCE_001", "population", "The study included adults with the condition."),
    )

    normalized = MedicalInsightAnalyzer(provider=ExtractiveMedicalAIProvider())._normalize_report(
        report,
        context,
    )

    question = normalized.question_suggestions[0]
    assert question.evidence_ids == ["EVIDENCE_001"]
    assert question.source_kind == "study_methods"
    assert question.source_id == "population"


def test_question_binding_replaces_provider_evidence_ids_with_source_evidence():
    report = _structured_report(_structured_question())
    payload = report.model_dump()
    payload["question_suggestions"][0]["evidence_ids"] = ["EVIDENCE_UNRELATED"]
    context = _context(
        ("EVIDENCE_001", "population", "The study included adults with the condition."),
    )

    normalized = MedicalInsightAnalyzer(provider=ExtractiveMedicalAIProvider())._normalize_report(
        MedicalInsightReport.model_validate(payload),
        context,
    )

    assert normalized.question_suggestions[0].evidence_ids == ["EVIDENCE_001"]


def test_question_binding_limits_source_evidence_to_five_ids():
    report = _structured_report(
        _structured_question(
            category="clarify_finding",
            topic="reported_result",
            source_kind="key_findings",
            source_id="finding_001",
        )
    )
    payload = report.model_dump()
    evidence_ids = [f"EVIDENCE_{index:03d}" for index in range(1, 8)]
    payload["key_findings"][0]["evidence_ids"] = evidence_ids
    report = MedicalInsightReport.model_validate(payload)
    context = _context(
        *(
            (evidence_id, "results", f"The study reported result {index}.")
            for index, evidence_id in enumerate(evidence_ids, start=1)
        )
    )

    normalized = MedicalInsightAnalyzer(provider=ExtractiveMedicalAIProvider())._normalize_report(
        report,
        context,
    )

    assert normalized.question_suggestions[0].evidence_ids == evidence_ids[:5]


def test_question_binding_does_not_silently_replace_incompatible_topic():
    report = _structured_report(
        _structured_question(
            category="applicability",
            topic="future_research",
            source_kind="future_research",
            source_id="future_001",
        )
    )
    context = _context(
        ("EVIDENCE_001", "population", "The study included adults with the condition."),
    )

    with pytest.raises(QuestionTemplateError, match="incompatible"):
        MedicalInsightAnalyzer(provider=ExtractiveMedicalAIProvider())._normalize_report(
            report,
            context,
        )


def test_analyzer_repairs_a_question_with_invalid_evidence():
    invalid = _structured_report(
        _structured_question(source_id="missing_population")
    ).model_dump()
    valid = _structured_report(_structured_question()).model_dump()
    provider = ExtractiveMedicalAIProvider()

    class RepairProvider(ExtractiveMedicalAIProvider):
        def __init__(self):
            self.calls = 0

        def generate(self, prompt, context):
            self.calls += 1
            return invalid if self.calls == 1 else valid

    repair_provider = RepairProvider()
    output = MedicalInsightAnalyzer(provider=repair_provider).run(
        [{"id": "chunk-1", "text": "The study included adults with the condition.", "section_type": "population"}],
        title="Example paper",
        document_kind="research_paper",
        language="en",
    )

    assert repair_provider.calls == 2
    assert output.questions.valid


def test_analyzer_replaces_free_form_question_with_controlled_template():
    unsafe = _report(
        _structured_question(question="Is migalastat a good option for me?")
    ).model_dump()
    unsafe["study_methods"] = {
        "population": {
            "value": "The study included adults with the condition.",
            "support_status": "supported",
            "evidence_ids": ["EVIDENCE_001"],
        }
    }

    class UnsafeProvider(ExtractiveMedicalAIProvider):
        def __init__(self):
            self.calls = 0

        def generate(self, prompt, context):
            self.calls += 1
            return unsafe

    provider = UnsafeProvider()
    output = MedicalInsightAnalyzer(provider=provider).run(
        [{"id": "chunk-1", "text": "The study included adults with the condition.", "section_type": "population"}],
        title="Example paper",
        document_kind="research_paper",
        language="en",
    )

    assert provider.calls == 1
    suggestion = output.report.question_suggestions[0]
    assert suggestion.topic == "study_population"
    assert suggestion.question == "Which people were included in this study, and who was not included?"
    assert "migalastat" not in suggestion.question
    assert validate_safety(output.report).valid


def test_analyzer_localizes_controlled_question_templates():
    payload = _structured_report(
        _structured_question(question="A free-form question from the provider?")
    ).model_dump()

    class Provider(ExtractiveMedicalAIProvider):
        def generate(self, prompt, context):
            return payload

    output = MedicalInsightAnalyzer(provider=Provider()).run(
        [{"id": "chunk-1", "text": "研究纳入成年人。", "section_type": "population"}],
        title="示例论文",
        document_kind="research_paper",
        language="zh-CN",
    )

    suggestion = output.report.question_suggestions[0]
    assert suggestion.question == "这项研究纳入了哪些人，没有纳入哪些人？"
    assert suggestion.rationale.startswith("原文描述了研究人群")


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
    assert "at most one question_suggestion for each topic" in prompt
