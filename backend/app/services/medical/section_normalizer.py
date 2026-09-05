"""Turn common paper headings into a small internal vocabulary."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.services.medical.models import MedicalSectionType


@dataclass(frozen=True)
class NormalizedSectionTitle:
    primary: str
    secondary: list[str] = field(default_factory=list)
    confidence: float = 0.0


# Longer aliases need to be checked before short aliases such as "method".
_ALIASES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("materials and methods", (MedicalSectionType.METHODS.value,)),
    ("study population", (MedicalSectionType.POPULATION.value,)),
    ("supplementary materials", (MedicalSectionType.SUPPLEMENTARY.value,)),
    ("adverse events", (MedicalSectionType.ADVERSE_EVENTS.value,)),
    ("adverse effects", (MedicalSectionType.ADVERSE_EVENTS.value,)),
    ("outcome measures", (MedicalSectionType.OUTCOMES.value,)),
    ("figure legend", (MedicalSectionType.FIGURE_CAPTION.value,)),
    ("figure caption", (MedicalSectionType.FIGURE_CAPTION.value,)),
    ("abstract", (MedicalSectionType.ABSTRACT.value,)),
    ("摘要", (MedicalSectionType.ABSTRACT.value,)),
    ("要旨", (MedicalSectionType.ABSTRACT.value,)),
    ("introduction", (MedicalSectionType.INTRODUCTION.value,)),
    ("background", (MedicalSectionType.INTRODUCTION.value,)),
    ("intro", (MedicalSectionType.INTRODUCTION.value,)),
    ("引言", (MedicalSectionType.INTRODUCTION.value,)),
    ("背景", (MedicalSectionType.INTRODUCTION.value,)),
    ("序論", (MedicalSectionType.INTRODUCTION.value,)),
    ("methods", (MedicalSectionType.METHODS.value,)),
    ("methodology", (MedicalSectionType.METHODS.value,)),
    ("method", (MedicalSectionType.METHODS.value,)),
    ("方法", (MedicalSectionType.METHODS.value,)),
    ("材料与方法", (MedicalSectionType.METHODS.value,)),
    ("participants", (MedicalSectionType.POPULATION.value,)),
    ("patients", (MedicalSectionType.POPULATION.value,)),
    ("subjects", (MedicalSectionType.POPULATION.value,)),
    ("population", (MedicalSectionType.POPULATION.value,)),
    ("研究对象", (MedicalSectionType.POPULATION.value,)),
    ("受试者", (MedicalSectionType.POPULATION.value,)),
    ("患者", (MedicalSectionType.POPULATION.value,)),
    ("intervention", (MedicalSectionType.INTERVENTION.value,)),
    ("treatment", (MedicalSectionType.INTERVENTION.value,)),
    ("exposure", (MedicalSectionType.INTERVENTION.value,)),
    ("干预", (MedicalSectionType.INTERVENTION.value,)),
    ("治疗", (MedicalSectionType.INTERVENTION.value,)),
    ("暴露", (MedicalSectionType.INTERVENTION.value,)),
    ("control", (MedicalSectionType.COMPARATOR.value,)),
    ("comparator", (MedicalSectionType.COMPARATOR.value,)),
    ("control group", (MedicalSectionType.COMPARATOR.value,)),
    ("对照", (MedicalSectionType.COMPARATOR.value,)),
    ("对照组", (MedicalSectionType.COMPARATOR.value,)),
    ("outcomes", (MedicalSectionType.OUTCOMES.value,)),
    ("endpoints", (MedicalSectionType.OUTCOMES.value,)),
    ("结局", (MedicalSectionType.OUTCOMES.value,)),
    ("终点", (MedicalSectionType.OUTCOMES.value,)),
    ("results", (MedicalSectionType.RESULTS.value,)),
    ("findings", (MedicalSectionType.RESULTS.value,)),
    ("结果", (MedicalSectionType.RESULTS.value,)),
    ("結果", (MedicalSectionType.RESULTS.value,)),
    ("safety", (MedicalSectionType.ADVERSE_EVENTS.value,)),
    ("不良事件", (MedicalSectionType.ADVERSE_EVENTS.value,)),
    ("安全性", (MedicalSectionType.ADVERSE_EVENTS.value,)),
    ("副作用", (MedicalSectionType.ADVERSE_EVENTS.value,)),
    ("discussion", (MedicalSectionType.DISCUSSION.value,)),
    ("讨论", (MedicalSectionType.DISCUSSION.value,)),
    ("討論", (MedicalSectionType.DISCUSSION.value,)),
    ("考察", (MedicalSectionType.DISCUSSION.value,)),
    ("limitations", (MedicalSectionType.LIMITATIONS.value,)),
    ("study limitations", (MedicalSectionType.LIMITATIONS.value,)),
    ("局限", (MedicalSectionType.LIMITATIONS.value,)),
    ("局限性", (MedicalSectionType.LIMITATIONS.value,)),
    ("限界", (MedicalSectionType.LIMITATIONS.value,)),
    ("conclusion", (MedicalSectionType.CONCLUSION.value,)),
    ("conclusions", (MedicalSectionType.CONCLUSION.value,)),
    ("结论", (MedicalSectionType.CONCLUSION.value,)),
    ("結論", (MedicalSectionType.CONCLUSION.value,)),
    ("references", (MedicalSectionType.REFERENCES.value,)),
    ("bibliography", (MedicalSectionType.REFERENCES.value,)),
    ("works cited", (MedicalSectionType.REFERENCES.value,)),
    ("参考文献", (MedicalSectionType.REFERENCES.value,)),
    ("参考資料", (MedicalSectionType.REFERENCES.value,)),
    ("supplementary", (MedicalSectionType.SUPPLEMENTARY.value,)),
    ("appendix", (MedicalSectionType.SUPPLEMENTARY.value,)),
    ("appendices", (MedicalSectionType.SUPPLEMENTARY.value,)),
    ("附录", (MedicalSectionType.SUPPLEMENTARY.value,)),
    ("付録", (MedicalSectionType.SUPPLEMENTARY.value,)),
)

_ALIASES_BY_LENGTH = tuple(sorted(_ALIASES, key=lambda item: len(item[0]), reverse=True))
_COMPOUND_SPLIT = re.compile(r"\s+(?:and|&)\s+|\s*/\s*|[、及与和]\s*", re.I)


def clean_heading(title: str) -> str:
    """Remove numbering and trailing punctuation from a heading."""
    value = re.sub(r"^\s*(?:section\s+)?(?:\d+(?:\.\d+)*|[IVX]+)[\s.)-]+", "", title, flags=re.I)
    value = re.sub(r"\s+", " ", value).strip(" \t:：.-–—")
    return value


def normalize_section_title(title: str) -> NormalizedSectionTitle:
    """Return the best known type without inventing a section."""
    cleaned = clean_heading(title)
    lowered = cleaned.casefold()
    direct = _match_alias(lowered)
    if direct:
        return NormalizedSectionTitle(
            direct[0], [item for item in direct[1] if item != direct[0]], 0.96
        )

    parts = [part.strip() for part in _COMPOUND_SPLIT.split(lowered) if part.strip()]
    found: list[str] = []
    for part in parts:
        match = _match_alias(part)
        if match and match[0] not in found:
            found.append(match[0])

    if found:
        return NormalizedSectionTitle(found[0], found[1:], 0.88)
    return NormalizedSectionTitle(MedicalSectionType.UNKNOWN.value, [], 0.2)


def _match_alias(value: str) -> tuple[str, tuple[str, ...]] | None:
    for alias, types in _ALIASES_BY_LENGTH:
        if value == alias:
            return types[0], types
    return None
