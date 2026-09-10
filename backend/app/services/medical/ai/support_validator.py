"""Check whether report wording stays within the cited source passages."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable

from app.services.medical.ai.context_builder import AnalysisContext
from app.services.medical.ai.models import EvidenceFinding, MedicalInsightReport


@dataclass
class SupportValidation:
    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


_NUMBER = re.compile(
    r"(?<![A-Za-z0-9])(?:\d+(?:\.\d+)?(?:\s*[-–]\s*\d+(?:\.\d+)?)?\s*%|"
    r"\d+(?:\.\d+)?\s*(?:mg|g|kg|mcg|μg|ug|mL|ml|L|mmHg|cm|mm|"
    r"years?|months?|days?|participants?|patients?|subjects?|人|例|名))(?![A-Za-z])",
    re.I,
)
_CAUSAL_CLAIM = re.compile(
    r"\b(?:causes?|caused|leads? to|resulted in|prevents?|cures?|proves?)\b|"
    r"(?:导致|造成|引起|预防了|治愈了|证明了)",
    re.I,
)
_NEGATED_CAUSAL_CLAIM = re.compile(
    r"\b(?:(?:do(?:es)?|did|can(?:not|'t)?|could|should|is|are|was|were)\s+not|"
    r"cannot|can't)\s+(?:prove|establish|show|demonstrate|mean)\b.{0,60}"
    r"\b(?:caus(?:e|es|ed|al|ation)|lead(?:s)?\s+to|result(?:s|ed)?\s+in)\b|"
    r"\bno evidence (?:that|of)\b.{0,60}\b(?:caus(?:e|es|ed|al|ation)|lead(?:s)?\s+to)\b|"
    r"(?:不能|无法|并不|不代表|并不意味着).{0,20}(?:证明|证实|表明|说明|意味着)?"
    r".{0,30}(?:因果|导致|造成|引起)",
    re.I | re.S,
)
_ASSOCIATION_SOURCE = re.compile(
    r"\b(?:associated with|association|correlated with|correlation|linked to)\b|"
    r"(?:相关|关联|相关性)",
    re.I,
)
_PRECLINICAL_SOURCE = re.compile(
    r"\b(?:mice|mouse|murine|rats?|animal model|in vitro|cell(?:ular)?|organoid)\b|"
    r"(?:小鼠|大鼠|动物实验|动物模型|体外|细胞实验|类器官)",
    re.I,
)
_HUMAN_EFFICACY_CLAIM = re.compile(
    r"\b(?:patients?|people|humans?)\b.{0,45}\b(?:effective|efficacy|improved|treats?|benefit)\b|"
    r"\b(?:effective|efficacy|improved|treats?|benefit)\b.{0,45}\b(?:patients?|people|humans?)\b|"
    r"(?:对患者|对人类|人体).{0,30}(?:有效|疗效|改善|治疗)",
    re.I | re.S,
)
_NEGATED_HUMAN_CLAIM = re.compile(
    r"\b(?:does not|cannot|is not evidence of)\b.{0,50}\b(?:human|patient|efficacy|effective)\b|"
    r"(?:不能|无法|不代表).{0,30}(?:人体|患者|疗效|有效)",
    re.I | re.S,
)
_NON_SIGNIFICANT_SOURCE = re.compile(
    r"\b(?:not statistically significant|no statistically significant difference|"
    r"no significant difference|non-significant)\b|"
    r"(?:无统计学意义|未见显著差异|差异无统计学意义)",
    re.I,
)
_NO_EFFECT_CLAIM = re.compile(
    r"\b(?:prov(?:es?|ed|en) (?:that )?(?:there is )?no effect|prov(?:es?|ed|en) ineffective|"
    r"ineffective|has no effect)\b|"
    r"(?:证明无效|没有任何效果|完全无效)",
    re.I,
)
_NEGATED_NO_EFFECT_CLAIM = re.compile(
    r"\b(?:(?:do(?:es)?|did|can(?:not|'t)?|could|should|is|are|was|were)\s+not|"
    r"cannot|can't)\s+(?:prove|establish|show|demonstrate|mean)\b.{0,60}"
    r"\b(?:ineffective|no effect)\b|"
    r"(?:不能|无法|并不|不代表|并不意味着).{0,30}(?:无效|没有(?:任何)?效果)",
    re.I | re.S,
)
_SPECULATIVE_SOURCE = re.compile(
    r"\b(?:may|might|could|suggests?|hypothes(?:is|ize|ized)|possibly)\b|"
    r"(?:可能|或许|提示|推测|假设)",
    re.I,
)
_CERTAIN_CLAIM = re.compile(
    r"\b(?:proves?|establishes?|confirms?|demonstrates conclusively)\b|"
    r"(?:证实了|证明了|明确表明|确定)",
    re.I,
)
_NEGATED_CERTAIN_CLAIM = re.compile(
    r"\b(?:(?:do(?:es)?|did|can(?:not|'t)?|could|should|is|are|was|were)\s+not|"
    r"cannot|can't)\s+(?:prove|establish|confirm|show|demonstrate|mean)\b|"
    r"(?:不能|无法|并不|不代表|并不意味着).{0,20}(?:证明|证实|确认|表明|说明|意味着)",
    re.I,
)


def validate_support(
    report: MedicalInsightReport,
    context: AnalysisContext,
) -> SupportValidation:
    """Reject high-confidence wording that is contradicted by cited text."""
    errors: list[str] = []
    evidence = context.evidence_by_id

    for label, statement, evidence_ids in _supported_statements(report):
        sources = [evidence[value].text for value in evidence_ids if value in evidence]
        if not sources:
            continue
        source_text = "\n".join(sources)
        claim_text = statement.strip()

        missing_numbers = [
            value for value in _numbers(claim_text) if value not in _numbers(source_text)
        ]
        if missing_numbers:
            errors.append(f"{label} contains numbers or units not found in its evidence")
        if (
            _ASSOCIATION_SOURCE.search(source_text)
            and _has_unnegated_claim(
                claim_text,
                _CAUSAL_CLAIM,
                _NEGATED_CAUSAL_CLAIM,
            )
        ):
            errors.append(f"{label} turns an association into causation")
        if (
            _PRECLINICAL_SOURCE.search(source_text)
            and _HUMAN_EFFICACY_CLAIM.search(claim_text)
            and not _NEGATED_HUMAN_CLAIM.search(claim_text)
        ):
            errors.append(f"{label} turns preclinical evidence into human efficacy")
        if (
            _NON_SIGNIFICANT_SOURCE.search(source_text)
            and _has_unnegated_claim(
                claim_text,
                _NO_EFFECT_CLAIM,
                _NEGATED_NO_EFFECT_CLAIM,
            )
        ):
            errors.append(f"{label} treats a non-significant result as proof of no effect")
        if (
            _SPECULATIVE_SOURCE.search(source_text)
            and _has_unnegated_claim(
                claim_text,
                _CERTAIN_CLAIM,
                _NEGATED_CERTAIN_CLAIM,
            )
        ):
            errors.append(f"{label} states a speculative source as established fact")

    return SupportValidation(valid=not errors, errors=list(dict.fromkeys(errors)))


def _supported_statements(
    report: MedicalInsightReport,
) -> Iterable[tuple[str, str, list[str]]]:
    yield "overview", report.overview.summary, report.overview.evidence_ids
    for field_name in (
        "key_findings",
        "limitations",
        "what_it_means",
        "what_it_does_not_mean",
        "applicability",
        "future_research",
    ):
        for index, item in enumerate(getattr(report, field_name), start=1):
            yield f"{field_name}[{index}]", _finding_text(item), item.evidence_ids
    for field_name, item in report.study_methods.model_dump().items():
        if item["support_status"] != "not_reported":
            yield f"study_methods.{field_name}", item["value"], item["evidence_ids"]


def _finding_text(item: EvidenceFinding) -> str:
    return f"{item.statement}\n{item.plain_explanation}"


def _numbers(text: str) -> set[str]:
    return {re.sub(r"\s+", "", match.group(0)).lower() for match in _NUMBER.finditer(text)}


def _has_unnegated_claim(
    text: str,
    claim_pattern: re.Pattern[str],
    negated_pattern: re.Pattern[str],
) -> bool:
    clauses = re.split(
        r"[。！？]+|(?<=[.!?])\s+|[\n;；]+|"
        r"\b(?:but|however|yet|nevertheless)\b|(?:但是|然而|不过|可是|但|却)",
        text,
        flags=re.I,
    )
    for clause in clauses:
        if claim_pattern.search(clause) and not negated_pattern.search(clause):
            return True
    return False
