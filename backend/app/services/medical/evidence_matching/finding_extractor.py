"""Extract deterministic, evidence-backed finding snapshots from a report."""

from __future__ import annotations

import re
from typing import Any, Iterable, Mapping

from pydantic import BaseModel, ValidationError

from app.services.medical.ai.models import MedicalInsightReport
from app.services.medical.evidence_matching.models import (
    FindingType,
    MatchableFinding,
)
from app.services.medical.terminology.loader import DiseaseOntology
from app.services.medical.terminology.normalizer import normalize_terminology_text


class FindingExtractionError(ValueError):
    """The persisted report cannot be converted into a safe finding snapshot."""


_SECTION_TYPES: tuple[tuple[str, FindingType], ...] = (
    ("key_findings", "key_finding"),
    ("limitations", "limitation"),
    ("what_it_means", "meaning"),
    ("what_it_does_not_mean", "not_meaning"),
    ("applicability", "applicability"),
    ("future_research", "future_research"),
)

_ENGLISH_WORD = re.compile(r"(?<![A-Za-z0-9])[A-Za-z][A-Za-z0-9]*(?:[-'][A-Za-z0-9]+)*(?![A-Za-z0-9])")
_MEASUREMENT = re.compile(
    r"\b\d+(?:\.\d+)?\s*(?:%|patients?|participants?|subjects?|years?|months?|mg|g|kg|mmhg|"
    r"ng|μ?g/ml|μ?mol/l|iu/l|m?iu/l|cells?/μl|/μl)\b",
    flags=re.IGNORECASE,
)
_STOPWORDS = {
    "a",
    "about",
    "analysis",
    "after",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "been",
    "being",
    "by",
    "can",
    "could",
    "did",
    "does",
    "disease",
    "for",
    "from",
    "has",
    "have",
    "in",
    "into",
    "is",
    "it",
    "its",
    "may",
    "more",
    "of",
    "on",
    "or",
    "paper",
    "patient",
    "patients",
    "people",
    "reported",
    "report",
    "research",
    "result",
    "results",
    "study",
    "studies",
    "than",
    "that",
    "the",
    "their",
    "these",
    "this",
    "to",
    "treatment",
    "use",
    "used",
    "using",
    "was",
    "were",
    "what",
    "which",
    "with",
    "without",
    "would",
    # These are intentionally not translated into English search terms.
    "患者",
    "疾病",
    "研究",
    "结果",
    "治疗",
    "分析",
}


class FindingExtractor:
    """Turn one validated report into a bounded set of matchable findings."""

    def __init__(
        self,
        *,
        ontology: DiseaseOntology | None = None,
        max_findings: int = 20,
    ) -> None:
        self.ontology = ontology
        self.max_findings = max(1, min(int(max_findings or 1), 20))

    def extract(
        self,
        report: MedicalInsightReport | Mapping[str, Any],
        *,
        detected_concepts: Iterable[Any] = (),
        controlled_terms: Iterable[str] = (),
        condition_terms: Iterable[str] = (),
        biomedical_terms: Iterable[str] = (),
        valid_evidence_ids: set[str] | None = None,
    ) -> list[MatchableFinding]:
        parsed_report = _coerce_report(report)
        concept_terms = _concept_terms(
            detected_concepts,
            ontology=self.ontology,
        )
        all_controlled = _unique_terms(
            [*controlled_terms, *concept_terms[0], *condition_terms, *biomedical_terms],
            limit=8,
        )
        conditions = _unique_terms(
            [*concept_terms[1], *condition_terms],
            limit=16,
        )
        biomedical = _unique_terms(
            [*concept_terms[2], *biomedical_terms],
            limit=16,
        )

        findings: list[MatchableFinding] = []
        seen_text: set[str] = set()
        seen_ids: set[str] = set()
        for field_name, finding_type in _SECTION_TYPES:
            values = getattr(parsed_report, field_name, ())
            for item in values:
                statement = _value(item, "statement").strip()
                if not statement:
                    continue
                evidence_ids = _clean_ids(_value(item, "evidence_ids"))
                if valid_evidence_ids is not None:
                    evidence_ids = [item for item in evidence_ids if item in valid_evidence_ids]
                if not evidence_ids:
                    continue
                normalized = normalize_terminology_text(statement)
                if not normalized or normalized in seen_text:
                    continue
                seen_text.add(normalized)

                source_id = _value(item, "id").strip()
                if not source_id:
                    source_id = f"{finding_type}_{len(findings) + 1:03d}"
                finding_id = source_id
                if finding_id in seen_ids:
                    finding_id = f"{finding_type}:{source_id}"
                finding_id = finding_id[:128]
                while finding_id in seen_ids:
                    finding_id = f"{finding_type}:{finding_id}"[:128]
                seen_ids.add(finding_id)

                keywords, phrases = _text_terms(statement, all_controlled)
                findings.append(
                    MatchableFinding(
                        finding_id=finding_id,
                        finding_type=finding_type,
                        statement=statement[:8000],
                        plain_explanation=_value(item, "plain_explanation").strip()[:8000],
                        evidence_ids=evidence_ids[:32],
                        normalized_text=normalized[:8000],
                        controlled_terms=all_controlled,
                        condition_terms=conditions,
                        biomedical_terms=biomedical,
                        keywords=keywords,
                        phrases=phrases,
                    )
                )
                if len(findings) >= self.max_findings:
                    return findings
        return findings


def extract_matchable_findings(
    report: MedicalInsightReport | Mapping[str, Any],
    *,
    detected_concepts: Iterable[Any] = (),
    ontology: DiseaseOntology | None = None,
    max_findings: int = 20,
    valid_evidence_ids: set[str] | None = None,
) -> list[MatchableFinding]:
    """Functional wrapper used by the matching repository and unit tests."""
    return FindingExtractor(ontology=ontology, max_findings=max_findings).extract(
        report,
        detected_concepts=detected_concepts,
        valid_evidence_ids=valid_evidence_ids,
    )


def _coerce_report(report: MedicalInsightReport | Mapping[str, Any]) -> MedicalInsightReport:
    if isinstance(report, MedicalInsightReport):
        return report
    if not isinstance(report, Mapping):
        raise FindingExtractionError("medical insight report must be an object")
    try:
        return MedicalInsightReport.model_validate(report)
    except (ValidationError, ValueError) as exc:
        raise FindingExtractionError("medical insight report is invalid") from exc


def _value(item: Any, field: str) -> Any:
    if isinstance(item, BaseModel):
        return getattr(item, field, "")
    if isinstance(item, Mapping):
        return item.get(field, "")
    return getattr(item, field, "")


def _clean_ids(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return list(dict.fromkeys(str(item).strip() for item in value if str(item).strip()))


def _concept_terms(
    concepts: Iterable[Any],
    *,
    ontology: DiseaseOntology | None,
) -> tuple[list[str], list[str], list[str]]:
    all_terms: list[str] = []
    condition_terms: list[str] = []
    biomedical_terms: list[str] = []
    for raw in concepts:
        concept = raw.model_dump() if isinstance(raw, BaseModel) else raw
        if not isinstance(concept, Mapping):
            continue
        concept_id = str(concept.get("concept_id") or "").strip()
        concept_type = str(concept.get("type") or "").strip().casefold()
        values = [
            concept.get("normalized"),
            concept.get("original"),
            concept.get("matched_alias"),
            concept.get("source_code"),
        ]
        if ontology and concept_id:
            record = ontology.get(concept_id)
            if record:
                values.extend([record.preferred_name_en, record.preferred_name_zh])
                values.extend(alias.text for alias in record.aliases[:8])
        terms = [str(value).strip() for value in values if str(value or "").strip()]
        all_terms.extend(terms)
        if concept_type in {"condition", "disease", "medical_condition"} or (
            concept_id.startswith("mesh:") or concept_id.startswith("orpha:")
        ):
            condition_terms.extend(terms)
        else:
            biomedical_terms.extend(terms)
    return (
        _unique_terms(all_terms, limit=8),
        _unique_terms(condition_terms, limit=16),
        _unique_terms(biomedical_terms, limit=16),
    )


def _text_terms(statement: str, controlled_terms: Iterable[str]) -> tuple[list[str], list[str]]:
    controlled_normalized = {
        normalize_terminology_text(term)
        for term in controlled_terms
        if normalize_terminology_text(term)
    }
    words = [match.group(0) for match in _ENGLISH_WORD.finditer(statement)]
    keywords: list[str] = []
    for word in words:
        normalized = word.casefold()
        if normalized in _STOPWORDS:
            continue
        if len(normalized) < 3 and not (word.isupper() and len(word) >= 2):
            continue
        if normalized in controlled_normalized:
            continue
        if normalized not in keywords:
            keywords.append(normalized)
    measurement_terms = [
        normalize_terminology_text(match.group(0))
        for match in _MEASUREMENT.finditer(statement)
    ]
    phrases: list[str] = []
    for phrase in _phrase_candidates(words):
        normalized = normalize_terminology_text(phrase)
        if normalized and normalized not in controlled_normalized and normalized not in phrases:
            phrases.append(normalized)
    for phrase in measurement_terms:
        if phrase not in phrases:
            phrases.append(phrase)
    return keywords[:10], phrases[:5]


def _phrase_candidates(words: list[str]) -> list[str]:
    content = [word for word in words if word.casefold() not in _STOPWORDS]
    candidates: list[str] = []
    # Longest phrases are more discriminating, while preserving source order.
    for size in range(min(5, len(content)), 1, -1):
        for start in range(0, len(content) - size + 1):
            phrase = " ".join(content[start : start + size])
            if len(phrase) <= 100 and phrase.casefold() not in candidates:
                candidates.append(phrase)
    return candidates[:12]


def _unique_terms(values: Iterable[Any], *, limit: int) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()
    for raw in values:
        term = str(raw or "").strip()
        normalized = normalize_terminology_text(term)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        terms.append(term)
        if len(terms) >= limit:
            break
    return terms
