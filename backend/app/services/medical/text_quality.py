"""Conservative quality checks for passages used as medical evidence."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class PassageQuality:
    usable: bool
    score: int
    reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "usable": self.usable,
            "score": self.score,
            "reasons": list(self.reasons),
        }


_MEANINGFUL = re.compile(
    r"[A-Za-zÀ-ÖØ-öø-ÿ0-9\u3400-\u4dbf\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]"
)
_SENTENCE_END = re.compile(r"[.!?。！？](?:\s|$)")
_BROKEN_HYPHEN = re.compile(r"\b[A-Za-z]{2,}-\s+[a-z]{2,}\b")
_INSERTED_HEADING = re.compile(
    r"(?:^|[.!?。！？]\s+)(?:objectives?|methods?|results?|conclusions?|"
    r"acknowledg(?:e)?ments?|references?)\s+(?-i:[A-Z])[a-z]",
    re.I,
)
_CITATION = re.compile(
    r"(?:\[\s*\d{1,3}(?:\s*[,–-]\s*\d{1,3})*\]|"
    r"\((?:[^()]{2,50},\s*)?(?:19|20)\d{2}[a-z]?\))"
)
_COLUMN_INTERLEAVE = re.compile(
    r"(?:\b(?:ary|orm|tients|cance|sults|troduction)[, ]+\b){1,2}",
    re.I,
)
_ADJACENT_DUPLICATE = re.compile(
    r"\b([A-Za-z][A-Za-z'-]{2,})\s+([A-Za-z][A-Za-z'-]{2,})\b"
)
_LOWERCASE_FRAGMENT = re.compile(
    r"^(?:ary|orm|tients?|cance|sults|troduction|nformation|ntervention|"
    r"ignifi|ethods?|esults?|onclusion)\b",
)
_REFERENCE_LIKE = re.compile(
    r"(?:\bdoi\s*:\s*10\.|https?://doi\.org/10\.|\b(?:pmid|issn)\s*[:#]?\s*\d+|"
    r"\b(?:intern\s+med|journal|vol(?:ume)?|suppl(?:ement)?)\b\s*\d{1,4}\s*[:;])",
    re.I,
)

_NON_MEDICAL = {
    "references",
    "reference",
    "bibliography",
    "works_cited",
    "reference_list",
    "references_and_bibliography",
    "supplementary",
    "acknowledgements",
    "acknowledgments",
    "funding",
    "author_contributions",
    "conflicts_of_interest",
}


def assess_passage(
    text: str,
    *,
    section_type: str = "",
    section_title: str = "",
    metadata: dict[str, Any] | None = None,
    source_warnings: Iterable[str] = (),
) -> PassageQuality:
    """Return a stable, explainable quality decision for one passage.

    This gate intentionally errs on the side of omission. A rejected passage
    can remain visible in the document browser, but cannot support a medical
    claim or a clinician question.
    """
    value = " ".join(str(text or "").split()).strip()
    metadata = metadata if isinstance(metadata, dict) else {}
    reasons: list[str] = []
    hard_reject = False

    if not value:
        return PassageQuality(False, 0, ("empty",))
    meaningful = len(_MEANINGFUL.findall(value))
    cjk_meaningful = len(re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]", value))
    if meaningful < 8 and not (cjk_meaningful >= 6 and cjk_meaningful >= meaningful * 0.5):
        reasons.append("too_few_meaningful_characters")
        hard_reject = True
    if not _MEANINGFUL.search(value):
        reasons.append("punctuation_only")
        hard_reject = True

    normalized_section = str(section_type or "").strip().lower().replace("-", "_").replace(" ", "_")
    if normalized_section in _NON_MEDICAL:
        reasons.append("non_medical_section")
        hard_reject = True

    block_type = str(
        metadata.get("pdf_block_type")
        or metadata.get("block_type")
        or ""
    ).strip().lower().replace("-", "_")
    inherited_flags = [
        str(flag).strip().lower()
        for flag in (
            *(metadata.get("quality_flags") or []),
            *(metadata.get("pdf_quality_flags") or []),
            *(metadata.get("extraction_warnings") or []),
            *source_warnings,
        )
        if str(flag).strip()
    ]
    if metadata.get("medical_evidence") is False or block_type in {
        "figure_caption",
        "table_caption",
        "header",
        "footer",
        "metadata",
        "heading",
        "page_text",
    }:
        reasons.append(
            "caption_body_mixed"
            if block_type in {"figure_caption", "table_caption"}
            else "header_footer_contamination"
            if block_type in {"header", "footer", "metadata"}
            else "heading_body_duplicated"
            if block_type == "heading"
            else "non_medical_block"
        )
        hard_reject = True
    for flag in inherited_flags:
        if flag not in reasons and flag in {
            "mixed_page_regions",
            "caption_body_mixed",
            "header_footer_contamination",
            "heading_body_duplicated",
            "reference_like",
        }:
            reasons.append(flag)
            hard_reject = True

    if any("unreadable" in flag for flag in inherited_flags):
        reasons.append("pdf_text_unreadable")
        hard_reject = True
    if any("ambiguous" in flag for flag in inherited_flags):
        reasons.append("pdf_layout_ambiguous")
        hard_reject = True

    if _COLUMN_INTERLEAVE.search(value):
        reasons.append("obvious_column_interleave")
        hard_reject = True

    if any(
        first.casefold() == second.casefold() and first != second
        for first, second in _ADJACENT_DUPLICATE.findall(value)
    ):
        reasons.append("adjacent_duplicate_words")
        hard_reject = True
    if _LOWERCASE_FRAGMENT.search(value):
        reasons.append("incomplete_sentence")
        hard_reject = True
    if _REFERENCE_LIKE.search(value) or len(_CITATION.findall(value)) >= 4:
        reasons.append("reference_like")
        hard_reject = True

    soft_flags: list[str] = []
    if _BROKEN_HYPHEN.search(value):
        # An unrepaired line-ending hyphen is unsafe evidence. In a two-column
        # PDF the next word may belong to the other column, so do not let this
        # passage reach the medical report as a supported field.
        soft_flags.append("broken_word_hyphen")
        hard_reject = True
    if _INSERTED_HEADING.search(value):
        soft_flags.append("inserted_heading")
    if not _balanced_brackets(value):
        soft_flags.append("unbalanced_brackets")
    if len(_CITATION.findall(value)) >= 3:
        soft_flags.append("citation_density")
    if not _SENTENCE_END.search(value) and len(value.split()) >= 12:
        soft_flags.append("no_sentence_boundary")
    reasons.extend(soft_flags)

    if len(soft_flags) >= 2:
        hard_reject = True
        reasons.append("combined_quality_risk")

    score = max(0, 100 - 35 * int(hard_reject) - 12 * len(soft_flags))
    return PassageQuality(
        usable=not hard_reject,
        score=score,
        reasons=tuple(dict.fromkeys(reasons)),
    )


def _balanced_brackets(value: str) -> bool:
    pairs = {"(": ")", "[": "]", "{": "}"}
    stack: list[str] = []
    for char in value:
        if char in pairs:
            stack.append(pairs[char])
        elif char in pairs.values():
            if not stack or stack.pop() != char:
                return False
    return not stack
