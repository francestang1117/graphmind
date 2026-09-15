"""Server-owned templates for safe V3 clinician discussion questions."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from pydantic import ValidationError

from app.services.medical.ai.context_builder import AnalysisContext
from app.services.medical.ai.models import MedicalInsightReport, QuestionSuggestion


_CATEGORY_TOPICS: dict[str, tuple[str, ...]] = {
    "clarify_finding": ("reported_result", "term_clarification"),
    "applicability": ("study_population", "study_design"),
    "study_limitation": ("study_limitation",),
    "monitoring_discussion": ("monitoring",),
    "research_option": ("future_research",),
}
_DEFAULT_TOPIC = {
    category: topics[0] for category, topics in _CATEGORY_TOPICS.items()
}

# These are report object paths, not evidence IDs. The provider may select a
# source object, but it cannot select arbitrary chunks to cite.
_TOPIC_SOURCES: dict[str, tuple[str, str | None]] = {
    "study_population": ("study_methods", "population"),
    "study_design": ("study_methods", "design"),
    "reported_result": ("key_findings", None),
    "term_clarification": ("medical_terms", None),
    "study_limitation": ("limitations", None),
    "monitoring": ("key_findings", None),
    "future_research": ("future_research", None),
}

_TEMPLATES: dict[str, dict[str, tuple[str, str]]] = {
    "en": {
        "study_population": (
            "Which people were included in this study, and who was not included?",
            "The source describes a study population, so a healthcare professional can help explain who the findings may apply to.",
        ),
        "study_design": (
            "What aspects of the study design affect who these findings may apply to?",
            "The source describes a study design, so a healthcare professional can help explain its limits for applying the findings.",
        ),
        "reported_result": (
            "What did the study report about this finding?",
            "The source reports a finding, so a healthcare professional can help clarify what the result means.",
        ),
        "term_clarification": (
            "Which terms in this finding should I ask a healthcare professional to explain?",
            "The source uses medical terms, so a healthcare professional can explain the parts that are difficult to understand.",
        ),
        "study_limitation": (
            "What limitation should I keep in mind when interpreting these findings?",
            "The source describes a limitation, so a healthcare professional can help explain how it affects interpretation.",
        ),
        "monitoring": (
            "Which outcomes or safety signals did the study monitor?",
            "The source describes monitored outcomes or safety signals, so a healthcare professional can help explain their meaning.",
        ),
        "future_research": (
            "What further research would help clarify these findings?",
            "The source points to an open research question, so a healthcare professional can help put the remaining uncertainty in context.",
        ),
    },
    "zh": {
        "study_population": (
            "这项研究纳入了哪些人，没有纳入哪些人？",
            "原文描述了研究人群，专业人员可以帮助解释这些结果可能适用于哪些人。",
        ),
        "study_design": (
            "研究设计中的哪些因素会影响这些结果适用于哪些人？",
            "原文描述了研究设计，专业人员可以帮助解释将结果推广到其他人时的限制。",
        ),
        "reported_result": (
            "这项研究报告了什么结果？",
            "原文报告了一个研究发现，专业人员可以帮助解释这个结果的含义。",
        ),
        "term_clarification": (
            "这项发现中的哪些术语需要请专业人员解释？",
            "原文使用了医学术语，专业人员可以帮助解释难以理解的部分。",
        ),
        "study_limitation": (
            "解读这些结果时需要注意哪些局限？",
            "原文描述了研究局限，专业人员可以帮助解释它对结果解读的影响。",
        ),
        "monitoring": (
            "研究监测了哪些结果或安全性信号？",
            "原文描述了监测的结果或安全性信号，专业人员可以帮助解释其含义。",
        ),
        "future_research": (
            "还需要开展什么研究来进一步明确这些结果？",
            "原文提出了尚未解决的研究问题，专业人员可以帮助说明剩余的不确定性。",
        ),
    },
    "ja": {
        "study_population": (
            "この研究にはどのような人が含まれ、誰が含まれていませんか？",
            "原文は研究対象者を説明しているため、専門家に結果がどのような人に当てはまり得るか確認できます。",
        ),
        "study_design": (
            "研究デザインのどの点が、結果を当てはめられる人に影響しますか？",
            "原文は研究デザインを説明しているため、結果を他の人に当てはめる際の限界を専門家に確認できます。",
        ),
        "reported_result": (
            "この研究はどのような結果を報告していますか？",
            "原文は研究結果を報告しているため、その意味を専門家に確認できます。",
        ),
        "term_clarification": (
            "この発見に含まれるどの用語を専門家に説明してもらうべきですか？",
            "原文には医学用語が含まれているため、理解しにくい部分を専門家に確認できます。",
        ),
        "study_limitation": (
            "この結果を解釈するとき、どのような限界に注意すべきですか？",
            "原文は研究の限界を説明しているため、解釈への影響を専門家に確認できます。",
        ),
        "monitoring": (
            "研究ではどのような結果や安全性の指標を監視しましたか？",
            "原文は監視した結果や安全性の指標を説明しているため、その意味を専門家に確認できます。",
        ),
        "future_research": (
            "この結果を明らかにするために、今後どのような研究が必要ですか？",
            "原文は未解決の研究課題を示しているため、残る不確実性を専門家に確認できます。",
        ),
    },
}


def normalize_question_suggestions(
    suggestions: Iterable[QuestionSuggestion],
    language: str,
    *,
    report: MedicalInsightReport,
    context: AnalysisContext | None = None,
) -> list[QuestionSuggestion]:
    """Bind provider intents to report fields and replace prose with a template."""
    language_key = _language_key(language)
    normalized: list[QuestionSuggestion] = []
    errors: list[str] = []
    seen_topics: set[tuple[str, str]] = set()
    for index, item in enumerate(suggestions, start=1):
        try:
            topic, question, rationale = _template_for(item, language_key)
            source_kind, source_id, evidence_ids = _resolve_source(
                item,
                topic,
                report,
                context,
            )
        except QuestionTemplateError as exc:
            errors.extend(f"question_suggestions[{index}]: {error}" for error in exc.errors)
            continue
        topic_key = (item.category, topic)
        if topic_key in seen_topics:
            continue
        seen_topics.add(topic_key)
        normalized.append(
            item.model_copy(
                update={
                    "topic": topic,
                    "question": question,
                    "rationale": rationale,
                    "source_kind": source_kind,
                    "source_id": source_id,
                    "evidence_ids": evidence_ids,
                }
            )
        )
    if errors:
        raise QuestionTemplateError(errors)
    return normalized


def normalize_saved_question_payload(
    values: Any,
    language: str,
    *,
    report: MedicalInsightReport | None = None,
) -> list[dict[str, Any]]:
    """Sanitize V3 question rows before returning an old saved report."""
    if not isinstance(values, list) or report is None:
        return []
    normalized: list[dict[str, Any]] = []
    seen_topics: set[tuple[str, str]] = set()
    for value in values:
        try:
            item = QuestionSuggestion.model_validate(value)
        except ValidationError:
            continue
        try:
            rows = normalize_question_suggestions([item], language, report=report)
        except QuestionTemplateError:
            # A saved row without a valid report source is not safe to show.
            continue
        for row in rows:
            topic_key = (row.category, row.topic or "")
            if topic_key in seen_topics:
                continue
            seen_topics.add(topic_key)
            normalized.append(row.model_dump(mode="json"))
    return normalized


def is_controlled_question(item: QuestionSuggestion, language: str) -> bool:
    """Check whether a persisted V3 suggestion uses its server template."""
    if not item.topic:
        return False
    try:
        topic, question, rationale = _template_for(item, _language_key(language))
    except QuestionTemplateError:
        return False
    return (
        item.topic == topic
        and item.question == question
        and item.rationale == rationale
    )


def _template_for(
    item: QuestionSuggestion,
    language_key: str,
) -> tuple[str, str, str]:
    allowed = _CATEGORY_TOPICS.get(item.category, ())
    if item.topic is None:
        topic = _DEFAULT_TOPIC.get(item.category, "reported_result")
    elif item.topic not in allowed:
        raise QuestionTemplateError(
            [f"topic {item.topic!r} is incompatible with category {item.category!r}"]
        )
    else:
        topic = item.topic
    question, rationale = _TEMPLATES[language_key][topic]
    return topic, question, rationale


class QuestionTemplateError(ValueError):
    """A question intent cannot be safely bound to a report source."""

    def __init__(self, errors: Iterable[str]):
        self.errors = list(dict.fromkeys(str(error) for error in errors if error))
        super().__init__("; ".join(self.errors) or "invalid question template")


def question_source_errors(
    item: QuestionSuggestion,
    report: MedicalInsightReport,
    context: AnalysisContext | None = None,
) -> list[str]:
    """Defensively verify the binding on a normalized question row."""
    if item.topic is None and item.source_kind is None and item.source_id is None:
        # Direct V2-style validation remains compatible. New V3 rows are
        # normalized before validation and always carry a source selector.
        return []
    try:
        topic, _question, _rationale = _template_for(item, _language_key(report.language))
        _source_kind, _source_id, evidence_ids = _resolve_source(
            item,
            topic,
            report,
            context,
        )
    except QuestionTemplateError as exc:
        return list(exc.errors)
    if item.evidence_ids != evidence_ids:
        return ["evidence_ids do not match the selected report source"]
    return []


def _resolve_source(
    item: QuestionSuggestion,
    topic: str,
    report: MedicalInsightReport,
    context: AnalysisContext | None = None,
) -> tuple[str, str, list[str]]:
    expected = _TOPIC_SOURCES.get(topic)
    if expected is None:
        raise QuestionTemplateError(
            [f"topic {topic!r} has no directly citable report source"]
        )
    expected_kind, fixed_id = expected
    source_kind = item.source_kind or (expected_kind if fixed_id else None)
    source_id = item.source_id or fixed_id
    if source_kind != expected_kind:
        raise QuestionTemplateError(
            [f"topic {topic!r} requires source_kind {expected_kind!r}"]
        )
    if not source_id:
        raise QuestionTemplateError(
            [f"topic {topic!r} requires a source_id for the selected report object"]
        )

    # QuestionSuggestion has a five-citation limit. Keep the binding
    # deterministic when a report field contains a broader citation set.
    evidence_ids = _source_evidence_ids(report, source_kind, source_id)[:5]
    if not evidence_ids:
        raise QuestionTemplateError(
            [f"source {source_kind}.{source_id} has no supported evidence"]
        )
    if context is not None:
        invalid_sections = _invalid_source_sections(topic, evidence_ids, context)
        if invalid_sections:
            raise QuestionTemplateError(
                [
                    f"source {source_kind}.{source_id} points to incompatible "
                    f"evidence section(s): {', '.join(invalid_sections)}"
                ]
            )
    return source_kind, source_id, evidence_ids


_SOURCE_SECTION_TYPES: dict[str, set[str]] = {
    "study_population": {
        "abstract",
        "introduction",
        "methods",
        "participants",
        "patients",
        "population",
        "scope",
        "study_population",
    },
    "study_design": {
        "abstract",
        "introduction",
        "methods",
        "population",
        "study_design",
    },
    "reported_result": {
        "abstract",
        "adverse_events",
        "conclusion",
        "discussion",
        "evidence",
        "outcomes",
        "recommendations",
        "result",
        "results",
    },
    "monitoring": {
        "abstract",
        "adverse_events",
        "conclusion",
        "discussion",
        "evidence",
        "outcomes",
        "recommendations",
        "result",
        "results",
    },
    "study_limitation": {"abstract", "discussion", "limitation", "limitations"},
    "future_research": {"abstract", "discussion", "future_research", "limitations"},
}


def _invalid_source_sections(
    topic: str,
    evidence_ids: Iterable[str],
    context: AnalysisContext,
) -> list[str]:
    allowed = _SOURCE_SECTION_TYPES.get(topic)
    if not allowed:
        return []
    invalid: list[str] = []
    for evidence_id in evidence_ids:
        evidence = context.evidence_by_id.get(evidence_id)
        if evidence is None:
            continue
        section_type = str(evidence.section_type or "unknown").strip().lower()
        if section_type not in allowed and section_type not in invalid:
            invalid.append(section_type)
    return invalid


def _source_evidence_ids(
    report: MedicalInsightReport,
    source_kind: str,
    source_id: str,
) -> list[str]:
    if source_kind == "study_methods":
        if source_id not in {"population", "design"}:
            return []
        attribute = getattr(report.study_methods, source_id)
        if attribute.support_status == "not_reported":
            return []
        return _unique_ids(attribute.evidence_ids)

    if source_kind == "key_findings":
        return _finding_evidence_ids(report.key_findings, source_id)
    if source_kind == "limitations":
        return _finding_evidence_ids(report.limitations, source_id)
    if source_kind == "future_research":
        return _finding_evidence_ids(report.future_research, source_id)
    if source_kind == "medical_terms":
        for item in report.medical_terms:
            if item.term == source_id:
                return _unique_ids(item.evidence_ids)
    return []


def _finding_evidence_ids(items: Iterable[Any], source_id: str) -> list[str]:
    for item in items:
        if item.id == source_id:
            return _unique_ids(item.evidence_ids)
    return []


def _unique_ids(values: Iterable[Any]) -> list[str]:
    return list(dict.fromkeys(str(value) for value in values if str(value)))


def _language_key(language: str) -> str:
    normalized = str(language or "").strip().lower()
    if normalized.startswith("zh"):
        return "zh"
    if normalized.startswith("ja") or normalized.startswith("jp"):
        return "ja"
    return "en"
