"""Build explainable, privacy-bounded PubMed queries."""

from __future__ import annotations

from datetime import date
import hashlib
import json
import re
from dataclasses import dataclass
from collections.abc import Iterable

from app.services.medical.literature.exceptions import LiteratureQueryError
from app.services.medical.literature.models import DetectedConcept, LiteratureQuery, LiteratureSort
from app.services.medical.literature.normalizer import clean_text
from app.services.medical.terminology import (
    ConceptSelection,
    DiseaseOntology,
    DiseaseMatchError,
    DiseaseMatcher,
    get_default_ontology,
)
from app.services.medical.terminology.normalizer import normalize_match_text


_EMAIL = re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b")
_PHONE = re.compile(r"(?<!\w)\+?\d[\d\s().-]{7,}\d(?!\w)")
_GOVERNMENT_ID = re.compile(r"(?<!\w)[0-9]{17}[0-9Xx](?!\w)")
_DATE = re.compile(r"(?<!\d)(?:19|20)\d{2}[年/.-]\d{1,2}(?:[月/.-]\d{1,2}日?)?(?!\d)")
_LAB_OR_RECORD_ID = re.compile(
    r"(?:"
    r"(?i:(?:病历|就诊|住院|检查|患者)\s*(?:编号|号|id|number|no\.?)?\s*"
    r"[:：#-]\s*[A-Za-z0-9_-]{3,})"
    r"|(?i:(?:patient|medical record|visit))\s+(?:"
    r"(?i:(?:id|number|no\.?)\s*[:#-]?\s*[A-Za-z0-9_-]{3,})"
    r"|[A-Z]{1,4}\d[A-Za-z0-9_-]{2,}|\d{4,}"
    r")"
    r")"
)
_UNRESOLVED_CJK_DISEASE = re.compile(
    r"[\u3400-\u4dbf\u4e00-\u9fff]{1,24}"
    r"(?:病|症|癌|炎|瘤|综合征|肌营养不良)"
)

@dataclass(frozen=True)
class _ConceptRule:
    concept_type: str
    normalized: str
    aliases: tuple[str, ...]
    pubmed_terms: tuple[str, ...]


_CONCEPT_RULES = (
    _ConceptRule(
        "organ_or_symptom",
        "renal function",
        ("肾功能", "renal function", "renal impairment", "kidney function", "kidney disease"),
        ('"Kidney Diseases"[MeSH Terms]', 'renal function[Title/Abstract]'),
    ),
    _ConceptRule(
        "organ_or_symptom",
        "liver function",
        ("肝功能", "liver function", "hepatic function"),
        ('"Liver Function Tests"[MeSH Terms]', 'liver function[Title/Abstract]'),
    ),
    _ConceptRule(
        "organ_or_symptom",
        "cardiomyopathy",
        ("心肌病", "cardiomyopathy"),
        ('"Cardiomyopathies"[MeSH Terms]', 'cardiomyopathy[Title/Abstract]'),
    ),
    _ConceptRule(
        "organ_or_symptom",
        "proteinuria",
        ("蛋白尿", "proteinuria"),
        ('"Proteinuria"[MeSH Terms]', 'proteinuria[Title/Abstract]'),
    ),
    _ConceptRule(
        "gene",
        "GLA",
        ("GLA gene", "GLA"),
        ('"GLA"[Title/Abstract]',),
    ),
    _ConceptRule(
        "drug",
        "enzyme replacement therapy",
        ("酶替代治疗", "enzyme replacement therapy"),
        ('"Enzyme Replacement Therapy"[MeSH Terms]', 'enzyme replacement therapy[Title/Abstract]'),
    ),
    _ConceptRule(
        "drug",
        "migalastat",
        ("米加司他", "migalastat"),
        ('migalastat[Title/Abstract]',),
    ),
)

_STUDY_TYPE_TERMS = {
    "systematic_review": '"Systematic Review"[Publication Type]',
    "systematic review": '"Systematic Review"[Publication Type]',
    "meta_analysis": '"Meta-Analysis"[Publication Type]',
    "meta-analysis": '"Meta-Analysis"[Publication Type]',
    "randomized_controlled_trial": '"Randomized Controlled Trial"[Publication Type]',
    "randomized controlled trial": '"Randomized Controlled Trial"[Publication Type]',
    "clinical_trial": '"Clinical Trial"[Publication Type]',
    "clinical trial": '"Clinical Trial"[Publication Type]',
    "observational_study": '"Observational Study"[Publication Type]',
    "observational study": '"Observational Study"[Publication Type]',
    "case_report": '"Case Reports"[Publication Type]',
    "case report": '"Case Reports"[Publication Type]',
    "guideline": '"Guideline"[Publication Type]',
}


def build_literature_query(
    question: str,
    *,
    ontology: DiseaseOntology | None = None,
    concept_selections: Iterable[ConceptSelection] | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    study_types: list[str] | None = None,
    sort: LiteratureSort = "relevance",
    max_results: int = 20,
    provider: str = "pubmed",
) -> LiteratureQuery:
    """Extract safe concepts and return the exact query shown for confirmation.

    Disease aliases are resolved locally before any PubMed clause is built.
    Ambiguous aliases return a previewable query object without an external
    query or fingerprint until the user selects a candidate.
    """
    raw_question = str(question or "").strip()
    if not raw_question:
        raise LiteratureQueryError(
            "A medical research question is required.",
            code="literature_question_required",
        )
    if len(raw_question) > 500:
        raise LiteratureQueryError(
            "The research question is too long.",
            code="literature_question_too_long",
        )
    if date_from and date_to and date_from > date_to:
        raise LiteratureQueryError(
            "The publication date range is invalid.",
            code="literature_invalid_date_range",
        )
    if sort not in {"relevance", "newest"}:
        raise LiteratureQueryError(
            "The literature sort is invalid.",
            code="literature_invalid_sort",
        )
    if not 1 <= int(max_results) <= 50:
        raise LiteratureQueryError(
            "The maximum result count must be between 1 and 50.",
            code="literature_invalid_max_results",
        )

    sanitized_question, _redactions = redact_sensitive_text(raw_question)
    if ontology is None:
        try:
            ontology = get_default_ontology()
        except Exception as exc:
            raise LiteratureQueryError(
                "The local disease ontology is unavailable.",
                code="literature_ontology_unavailable",
            ) from exc
    selections = tuple(concept_selections or ())
    try:
        resolution = DiseaseMatcher(ontology).resolve(sanitized_question, selections)
    except DiseaseMatchError as exc:
        raise LiteratureQueryError(
            "The selected disease concept is not valid for this question.",
            code="literature_invalid_concept_selection",
        ) from exc
    if _has_unresolved_cjk_disease(sanitized_question, resolution.matches):
        raise LiteratureQueryError(
            "No medical concepts could be identified in the question.",
            code="literature_no_medical_concepts",
        )
    concepts = _ontology_detected_concepts(resolution.matches, selections, ontology)
    concepts.extend(_extract_concepts(sanitized_question))
    if not concepts and not resolution.unresolved_matches:
        raise LiteratureQueryError(
            "No medical concepts could be identified in the question.",
            code="literature_no_medical_concepts",
        )

    normalized_types = _normalize_study_types(study_types or [])
    selected_concept_ids = [
        concept.concept_id
        for concept in concepts
        if concept.concept_id and concept.source == "local_ontology"
    ]
    selected_concept_ids = list(dict.fromkeys(selected_concept_ids))
    if resolution.unresolved_matches:
        return LiteratureQuery(
            question=sanitized_question,
            sanitized_question=sanitized_question,
            redacted_fields=_redactions,
            detected_concepts=concepts,
            resolution_status="needs_confirmation",
            ambiguous_concepts=list(resolution.unresolved_matches),
            ontology_version=ontology.version,
            selected_concept_ids=selected_concept_ids,
            date_from=date_from,
            date_to=date_to,
            study_types=normalized_types,
            sort=sort,
            max_results=int(max_results),
            provider=provider,
        )

    clauses = [_concept_clause(concept, ontology=ontology) for concept in concepts]
    clauses.extend(_STUDY_TYPE_TERMS[item] for item in normalized_types)
    if date_from or date_to:
        clauses.append(_date_clause(date_from, date_to))
    normalized_query = " AND ".join(f"({clause})" for clause in clauses)
    fingerprint = _query_fingerprint(
        normalized_query,
        provider=provider,
        date_from=date_from,
        date_to=date_to,
        study_types=normalized_types,
        sort=sort,
        max_results=int(max_results),
        ontology_version=ontology.version,
        selected_concept_ids=selected_concept_ids,
    )
    return LiteratureQuery(
        question=sanitized_question,
        sanitized_question=sanitized_question,
        redacted_fields=_redactions,
        normalized_query=normalized_query,
        detected_concepts=concepts,
        date_from=date_from,
        date_to=date_to,
        study_types=normalized_types,
        sort=sort,
        max_results=int(max_results),
        provider=provider,
        ontology_version=ontology.version,
        selected_concept_ids=selected_concept_ids,
        query_hash=fingerprint,
    )


def redact_sensitive_text(text: str) -> tuple[str, list[str]]:
    """Remove direct identifiers before a question can become an external term."""
    redactions: list[str] = []
    value = text
    patterns = (
        ("email", _EMAIL),
        ("government_id", _GOVERNMENT_ID),
        ("date", _DATE),
        ("phone", _PHONE),
        ("record_id", _LAB_OR_RECORD_ID),
    )
    for label, pattern in patterns:
        value, count = pattern.subn("[REDACTED]", value)
        if count:
            redactions.append(label)
    return clean_text(value), redactions


def _extract_concepts(question: str) -> list[DetectedConcept]:
    """Extract only the non-disease rules retained for the legacy boundary."""
    concepts: list[DetectedConcept] = []
    seen: set[str] = set()

    for rule in sorted(
        (item for item in _CONCEPT_RULES if item.concept_type != "condition"),
        key=lambda item: max(map(len, item.aliases)),
        reverse=True,
    ):
        if rule.normalized in seen:
            continue
        for alias in rule.aliases:
            match = _find_alias_match(question, rule, alias)
            if match:
                concepts.append(
                    DetectedConcept(
                        type=rule.concept_type,
                        original=question[match.start() : match.end()],
                        normalized=rule.normalized,
                        source="legacy_rule",
                        matched_alias=alias,
                        match_type="exact",
                    )
                )
                seen.add(rule.normalized)
                break

    return concepts[:8]


def _ontology_detected_concepts(
    matches: Iterable,
    selections: Iterable[ConceptSelection],
    ontology: DiseaseOntology,
) -> list[DetectedConcept]:
    selection_map = {selection.match_id: selection.concept_id for selection in selections}
    concepts: list[DetectedConcept] = []
    seen: set[str] = set()
    for match in matches:
        if match.status == "needs_confirmation":
            selected_id = selection_map.get(match.match_id)
            if selected_id is None:
                continue
        else:
            selected_id = match.candidates[0].concept_id
        candidate = next(
            (item for item in match.candidates if item.concept_id == selected_id),
            None,
        )
        concept = ontology.get(selected_id)
        if candidate is None or concept is None or concept.concept_id in seen:
            continue
        concepts.append(
            DetectedConcept(
                type="condition",
                original=match.matched_text,
                normalized=concept.preferred_name_en,
                concept_id=concept.concept_id,
                source="local_ontology",
                source_code=concept.mesh_id or concept.orpha_code or concept.concept_id,
                matched_alias=candidate.matched_alias,
                match_type="dictionary",
                ontology_version=ontology.version,
            )
        )
        seen.add(concept.concept_id)
    return concepts


def _has_unresolved_cjk_disease(question: str, matches: Iterable) -> bool:
    """Reject likely unknown Chinese disease names before mixing other rules."""
    remaining = normalize_match_text(question)
    for match in sorted(matches, key=lambda item: len(item.normalized_text), reverse=True):
        remaining = remaining.replace(match.normalized_text, " ", 1)
    return _UNRESOLVED_CJK_DISEASE.search(remaining) is not None


def _find_alias_match(question: str, rule: _ConceptRule, alias: str) -> re.Match[str] | None:
    """Match English aliases as words so short gene symbols cannot hit substrings."""
    if rule.concept_type == "gene" and alias == "GLA":
        return re.search(r"(?<![A-Za-z0-9])GLA(?![A-Za-z0-9])", question)
    if re.search(r"[A-Za-z]", alias):
        pattern = r"(?<![A-Za-z0-9])" + re.escape(alias) + r"(?![A-Za-z0-9])"
        return re.search(pattern, question, flags=re.IGNORECASE)
    return re.search(re.escape(alias), question)


def _concept_clause(concept: DetectedConcept, *, ontology: DiseaseOntology) -> str:
    if concept.source == "local_ontology" and concept.concept_id:
        ontology_concept = ontology.get(concept.concept_id)
        if ontology_concept is None:
            raise LiteratureQueryError(
                "The selected disease concept is no longer available.",
                code="literature_concept_not_found",
            )
        return " OR ".join(ontology_concept.pubmed_terms)
    rule = next(
        (item for item in _CONCEPT_RULES if item.normalized == concept.normalized),
        None,
    )
    if rule:
        return " OR ".join(rule.pubmed_terms)
    return f"{_quote_term(concept.normalized)}[Title/Abstract]"


def _quote_term(value: str) -> str:
    safe = re.sub(r"[^\w\- ]+", " ", value, flags=re.UNICODE)
    return f'"{clean_text(safe)}"'


def _normalize_study_types(values: list[str]) -> list[str]:
    normalized: list[str] = []
    for raw_value in values:
        value = clean_text(raw_value).casefold().replace("  ", " ")
        if value not in _STUDY_TYPE_TERMS:
            raise LiteratureQueryError(
                "One or more study type filters are not supported.",
                code="literature_invalid_study_type",
            )
        canonical = value.replace(" ", "_").replace("-", "_")
        if canonical not in normalized:
            normalized.append(canonical)
    return normalized


def _date_clause(date_from: date | None, date_to: date | None) -> str:
    start = date_from.isoformat() if date_from else "1800-01-01"
    end = date_to.isoformat() if date_to else "3000-12-31"
    return f'"{start}"[Date - Publication] : "{end}"[Date - Publication]'


def _query_fingerprint(
    normalized_query: str,
    *,
    provider: str,
    ontology_version: str,
    selected_concept_ids: list[str],
    date_from: date | None,
    date_to: date | None,
    study_types: list[str],
    sort: str,
    max_results: int,
) -> str:
    payload = {
        "provider": provider.strip().lower(),
        "query": normalized_query,
        "ontology_version": ontology_version,
        "selected_concept_ids": sorted(selected_concept_ids),
        "date_from": date_from.isoformat() if date_from else None,
        "date_to": date_to.isoformat() if date_to else None,
        "study_types": list(study_types),
        "sort": sort,
        "max_results": max_results,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
