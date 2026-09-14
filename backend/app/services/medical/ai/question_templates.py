"""Server-owned templates for safe V3 clinician discussion questions."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from pydantic import ValidationError

from app.services.medical.ai.models import QuestionSuggestion


_CATEGORY_TOPICS: dict[str, tuple[str, ...]] = {
    "clarify_finding": ("reported_result", "term_clarification"),
    "applicability": ("study_population", "study_design"),
    "study_limitation": ("study_limitation",),
    "evidence_gap": ("evidence_gap",),
    "monitoring_discussion": ("monitoring",),
    "research_option": ("future_research",),
}
_DEFAULT_TOPIC = {
    category: topics[0] for category, topics in _CATEGORY_TOPICS.items()
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
        "evidence_gap": (
            "What important information was not reported in the available evidence?",
            "The source may leave information unreported, so a healthcare professional can help identify what still needs clarification.",
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
        "evidence_gap": (
            "现有证据没有报告哪些重要信息？",
            "原文可能没有报告部分信息，专业人员可以帮助确认哪些问题仍需澄清。",
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
        "evidence_gap": (
            "利用できる証拠で報告されていない重要な情報は何ですか？",
            "原文に報告されていない情報がある可能性があるため、残る疑問を専門家に確認できます。",
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
) -> list[QuestionSuggestion]:
    """Replace provider prose with a safe template selected by intent."""
    language_key = _language_key(language)
    normalized: list[QuestionSuggestion] = []
    for item in suggestions:
        topic, question, rationale = _template_for(item, language_key)
        normalized.append(
            item.model_copy(
                update={
                    "topic": topic,
                    "question": question,
                    "rationale": rationale,
                }
            )
        )
    return normalized


def normalize_saved_question_payload(
    values: Any,
    language: str,
) -> list[dict[str, Any]]:
    """Sanitize V3 question rows before returning an old saved report."""
    if not isinstance(values, list):
        return []
    normalized: list[dict[str, Any]] = []
    for value in values:
        try:
            item = QuestionSuggestion.model_validate(value)
        except ValidationError:
            continue
        normalized.extend(
            item.model_dump(mode="json")
            for item in normalize_question_suggestions([item], language)
        )
    return normalized


def is_controlled_question(item: QuestionSuggestion, language: str) -> bool:
    """Check whether a persisted V3 suggestion uses its server template."""
    if not item.topic:
        return False
    topic, question, rationale = _template_for(item, _language_key(language))
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
    topic = item.topic if item.topic in allowed else _DEFAULT_TOPIC.get(
        item.category,
        "reported_result",
    )
    question, rationale = _TEMPLATES[language_key][topic]
    return topic, question, rationale


def _language_key(language: str) -> str:
    normalized = str(language or "").strip().lower()
    if normalized.startswith("zh"):
        return "zh"
    if normalized.startswith("ja") or normalized.startswith("jp"):
        return "ja"
    return "en"
