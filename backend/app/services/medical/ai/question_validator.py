"""Validate source-backed questions for discussion with a healthcare professional."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.services.medical.ai.context_builder import AnalysisContext
from app.services.medical.ai.models import MedicalInsightReport


_REFERENCE_SECTION_TYPES = {
    "references",
    "reference",
    "bibliography",
    "works_cited",
    "reference_list",
    "references_and_bibliography",
}

_QUESTION_MARK = re.compile(r"[?？]$")
_ENGLISH_QUESTION_START = re.compile(
    r"^\s*(?:what|which|who|when|where|why|how|could|can|should|would|"
    r"is|are|does|do)\b",
    re.IGNORECASE,
)
_CJK_QUESTION_MARKERS = re.compile(
    r"(?:什么|哪些|哪种|谁|何时|哪里|为什么|为何|如何|能否|是否|可以|应该|需要|怎样)"
)
_VAGUE_QUESTION = re.compile(
    r"^(?:what should I do|what now|is it useful|does it work|should I worry|"
    r"我该怎么办|怎么办|有用吗|有效吗|我要治疗吗|需要治疗吗|严重吗)[?？。！!]*$",
    re.IGNORECASE,
)


@dataclass
class QuestionValidation:
    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def validate_questions(
    report: MedicalInsightReport,
    context: AnalysisContext,
) -> QuestionValidation:
    """Require each structured question to be useful, bounded, and cited."""
    errors: list[str] = []
    seen_questions: set[str] = set()
    seen_ids: set[str] = set()
    evidence = context.evidence_by_id

    if len(report.question_suggestions) > 5:
        errors.append("question_suggestions has more than 5 items")

    for index, item in enumerate(report.question_suggestions, start=1):
        label = f"question_suggestions[{index}]"
        normalized = normalize_question(item.question)
        if item.id in seen_ids:
            errors.append(f"{label} duplicates another question id")
        seen_ids.add(item.id)
        if normalized in seen_questions:
            errors.append(f"{label} duplicates another question")
        seen_questions.add(normalized)

        if not _is_question(item.question):
            errors.append(f"{label} is not phrased as a question")
        if _is_vague(item.question):
            errors.append(f"{label} is too vague to discuss the source document")
        if not item.evidence_ids:
            errors.append(f"{label} has no evidence_ids")
            continue
        if len(item.evidence_ids) != len(set(item.evidence_ids)):
            errors.append(f"{label} contains duplicate evidence_ids")
        if len(item.evidence_ids) > 5:
            errors.append(f"{label} cites more than 5 evidence ids")

        item_valid = True
        for evidence_id in item.evidence_ids:
            source = evidence.get(evidence_id)
            if source is None:
                errors.append(f"{label} cites unknown evidence id {evidence_id}")
                item_valid = False
                continue
            if _section_key(source.section_type) in _REFERENCE_SECTION_TYPES:
                errors.append(f"{label} cites a references section")
                item_valid = False
        if not item_valid:
            continue

    return QuestionValidation(valid=not errors, errors=list(dict.fromkeys(errors)))


def normalize_question(value: str) -> str:
    """Normalize harmless whitespace and terminal punctuation for deduplication."""
    return re.sub(r"\s+", "", str(value or "")).casefold().rstrip("?？。！!")


def _is_question(value: str) -> bool:
    normalized = " ".join(str(value or "").split()).strip()
    return bool(
        _QUESTION_MARK.search(normalized)
        or _ENGLISH_QUESTION_START.search(normalized)
        or _CJK_QUESTION_MARKERS.search(normalized)
    )


def _is_vague(value: str) -> bool:
    normalized = " ".join(str(value or "").split()).strip()
    if _VAGUE_QUESTION.fullmatch(normalized):
        return True
    compact = normalize_question(normalized)
    return len(compact) < 8


def _section_key(value: str) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
