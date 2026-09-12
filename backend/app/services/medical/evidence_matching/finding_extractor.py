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
from app.services.medical.terminology.matcher import DiseaseMatcher
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
        analysis_concepts: Iterable[Any] | None = None,
        candidate_concepts: Iterable[Any] | None = None,
        evidence_text_by_id: Mapping[str, str] | None = None,
        controlled_terms: Iterable[str] = (),
        condition_terms: Iterable[str] = (),
        biomedical_terms: Iterable[str] = (),
        valid_evidence_ids: set[str] | None = None,
    ) -> list[MatchableFinding]:
        parsed_report = _coerce_report(report)
        legacy_concept_mode = analysis_concepts is None and candidate_concepts is None
        if legacy_concept_mode:
            analysis_concepts_list = list(detected_concepts)
            candidate_concepts_list = analysis_concepts_list
        else:
            analysis_concepts_list = list(analysis_concepts or ())
            candidate_concepts_list = list(candidate_concepts or detected_concepts)
        analysis_terms = _concept_terms(analysis_concepts_list, ontology=self.ontology)
        candidate_terms = _concept_terms(candidate_concepts_list, ontology=self.ontology)
        all_controlled = _unique_terms(
            [
                *controlled_terms,
                *analysis_terms[0],
                *(candidate_terms[0] if legacy_concept_mode else []),
                *condition_terms,
                *biomedical_terms,
            ],
            limit=8,
        )
        global_conditions = _unique_terms([*analysis_terms[1], *condition_terms], limit=16)
        global_biomedical = _unique_terms([*analysis_terms[2], *biomedical_terms], limit=16)
        candidate_condition_ids = _concept_ids(candidate_concepts_list, condition_only=True)
        analysis_condition_ids = _concept_ids(analysis_concepts_list, condition_only=True)

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
                finding_id = _unique_finding_id(source_id, finding_type, seen_ids)
                seen_ids.add(finding_id)

                if legacy_concept_mode:
                    conditions = global_conditions
                    condition_status = "matched" if conditions else "unknown"
                else:
                    finding_text = _finding_text(
                        statement,
                        _value(item, "plain_explanation"),
                        evidence_ids,
                        evidence_text_by_id or {},
                    )
                    local_analysis_ids = _condition_ids_in_text(
                        finding_text,
                        ontology=self.ontology,
                    )
                    if not local_analysis_ids and len(analysis_condition_ids) == 1:
                        local_analysis_ids = set(analysis_condition_ids)
                    shared_ids = local_analysis_ids & candidate_condition_ids
                    if shared_ids:
                        conditions = _condition_terms_for_ids(
                            candidate_concepts_list,
                            shared_ids,
                            ontology=self.ontology,
                        )
                        condition_status = "matched" if conditions else "unknown"
                    elif local_analysis_ids and candidate_condition_ids:
                        conditions = []
                        condition_status = "mismatch"
                    elif candidate_condition_ids and analysis_condition_ids:
                        conditions = []
                        condition_status = "mismatch"
                    else:
                        conditions = []
                        condition_status = "unknown"

                finding_controlled = _unique_terms(
                    [
                        *controlled_terms,
                        *global_biomedical,
                        *conditions,
                    ],
                    limit=8,
                )
                keywords, phrases = _text_terms(statement, finding_controlled)
                findings.append(
                    MatchableFinding(
                        finding_id=finding_id,
                        finding_type=finding_type,
                        statement=statement[:8000],
                        plain_explanation=_value(item, "plain_explanation").strip()[:8000],
                        evidence_ids=evidence_ids[:32],
                        normalized_text=normalized[:8000],
                        controlled_terms=finding_controlled or all_controlled,
                        condition_terms=conditions,
                        biomedical_terms=global_biomedical,
                        keywords=keywords,
                        phrases=phrases,
                        condition_status=condition_status,
                    )
                )
                if len(findings) >= self.max_findings:
                    return findings
        return findings


def extract_matchable_findings(
    report: MedicalInsightReport | Mapping[str, Any],
    *,
    detected_concepts: Iterable[Any] = (),
    analysis_concepts: Iterable[Any] | None = None,
    candidate_concepts: Iterable[Any] | None = None,
    evidence_text_by_id: Mapping[str, str] | None = None,
    ontology: DiseaseOntology | None = None,
    max_findings: int = 20,
    valid_evidence_ids: set[str] | None = None,
) -> list[MatchableFinding]:
    """Functional wrapper used by the matching repository and unit tests."""
    return FindingExtractor(ontology=ontology, max_findings=max_findings).extract(
        report,
        detected_concepts=detected_concepts,
        analysis_concepts=analysis_concepts,
        candidate_concepts=candidate_concepts,
        evidence_text_by_id=evidence_text_by_id,
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


def extract_report_condition_concepts(
    report: MedicalInsightReport | Mapping[str, Any],
    *,
    ontology: DiseaseOntology | None,
    evidence_texts: Iterable[str] = (),
) -> list[dict[str, Any]]:
    """Extract report-owned condition concepts without trusting search input."""
    if ontology is None:
        return []
    parsed_report = _coerce_report(report)
    texts = [
        _value(parsed_report.overview, "title"),
        _value(parsed_report.overview, "summary"),
        _value(parsed_report.overview, "study_type"),
    ]
    for field_name, _finding_type in _SECTION_TYPES:
        for item in getattr(parsed_report, field_name, ()):
            texts.extend((_value(item, "statement"), _value(item, "plain_explanation")))
    for item in parsed_report.medical_terms:
        texts.extend((_value(item, "term"), _value(item, "explanation")))
    texts.extend(str(value or "") for value in evidence_texts)
    return _concepts_from_texts(texts, ontology=ontology)


def _concepts_from_texts(
    texts: Iterable[Any],
    *,
    ontology: DiseaseOntology,
) -> list[dict[str, Any]]:
    matcher = DiseaseMatcher(ontology)
    concepts: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for raw_text in texts:
        text = str(raw_text or "").strip()
        if not text:
            continue
        for match in matcher.find_matches(text):
            if match.status != "ready" or len(match.candidates) != 1:
                continue
            candidate = match.candidates[0]
            if candidate.resolution != "automatic" or candidate.concept_id in seen_ids:
                continue
            concept = ontology.get(candidate.concept_id)
            if concept is None:
                continue
            seen_ids.add(concept.concept_id)
            concepts.append(
                {
                    "type": "condition",
                    "original": match.matched_text,
                    "normalized": concept.preferred_name_en,
                    "concept_id": concept.concept_id,
                    "source": "local_ontology",
                    "source_code": concept.mesh_id or concept.orpha_code or "",
                }
            )
    return concepts


def _condition_ids_in_text(text: str, *, ontology: DiseaseOntology | None) -> set[str]:
    if ontology is None or not text.strip():
        return set()
    return {
        candidate.concept_id
        for match in DiseaseMatcher(ontology).find_matches(text)
        if match.status == "ready" and len(match.candidates) == 1
        for candidate in match.candidates
        if candidate.resolution == "automatic"
    }


def _concept_ids(concepts: Iterable[Any], *, condition_only: bool) -> set[str]:
    result: set[str] = set()
    for raw in concepts:
        concept = raw.model_dump() if isinstance(raw, BaseModel) else raw
        if not isinstance(concept, Mapping):
            continue
        concept_id = str(concept.get("concept_id") or "").strip()
        concept_type = str(concept.get("type") or "").strip().casefold()
        is_condition = concept_type in {"condition", "disease", "medical_condition"} or (
            concept_id.startswith("mesh:") or concept_id.startswith("orpha:")
        )
        if concept_id and is_condition == condition_only:
            result.add(concept_id)
    return result


def _condition_terms_for_ids(
    concepts: Iterable[Any],
    concept_ids: set[str],
    *,
    ontology: DiseaseOntology | None,
) -> list[str]:
    values: list[str] = []
    for raw in concepts:
        concept = raw.model_dump() if isinstance(raw, BaseModel) else raw
        if not isinstance(concept, Mapping):
            continue
        if str(concept.get("concept_id") or "").strip() not in concept_ids:
            continue
        values.extend(
            _concept_terms([concept], ontology=ontology)[1]
        )
    return _unique_terms(values, limit=16)


def _finding_text(
    statement: str,
    plain_explanation: Any,
    evidence_ids: Iterable[str],
    evidence_text_by_id: Mapping[str, str],
) -> str:
    texts = [statement, str(plain_explanation or "")]
    texts.extend(evidence_text_by_id.get(evidence_id, "") for evidence_id in evidence_ids)
    return "\n".join(text for text in texts if text).strip()


def _unique_finding_id(source_id: str, finding_type: FindingType, seen_ids: set[str]) -> str:
    base = source_id[:128]
    if base not in seen_ids:
        return base
    for counter in range(2, 10000):
        suffix = f":{counter:04d}"
        candidate = f"{base[:128 - len(suffix)]}{suffix}"
        if candidate not in seen_ids:
            return candidate
    raise FindingExtractionError(f"too many duplicate finding ids for {finding_type}")


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
