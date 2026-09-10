"""Build explainable, privacy-bounded PubMed queries."""

from __future__ import annotations

from datetime import date
import hashlib
import json
import re
from dataclasses import dataclass

from app.services.medical.literature.exceptions import LiteratureQueryError
from app.services.medical.literature.models import DetectedConcept, LiteratureQuery, LiteratureSort
from app.services.medical.literature.normalizer import clean_text


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

_STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "can",
    "does",
    "for",
    "from",
    "have",
    "how",
    "is",
    "new",
    "of",
    "on",
    "or",
    "research",
    "treatment",
    "treatments",
    "therapy",
    "therapies",
    "medication",
    "medications",
    "the",
    "this",
    "what",
    "with",
}


@dataclass(frozen=True)
class _ConceptRule:
    concept_type: str
    normalized: str
    aliases: tuple[str, ...]
    pubmed_terms: tuple[str, ...]


_CONCEPT_RULES = (
    _ConceptRule(
        "condition",
        "Fabry disease",
        ("法布雷病", "fabry disease", "fabry's disease"),
        ('"Fabry Disease"[MeSH Terms]', '"Fabry disease"[Title/Abstract]'),
    ),
    _ConceptRule(
        "condition",
        "Diabetes Mellitus",
        ("糖尿病", "diabetes mellitus", "diabetes"),
        ('"Diabetes Mellitus"[MeSH Terms]', 'diabetes[Title/Abstract]'),
    ),
    _ConceptRule(
        "condition",
        "Hypertension",
        ("高血压", "hypertension"),
        ('"Hypertension"[MeSH Terms]', 'hypertension[Title/Abstract]'),
    ),
    _ConceptRule(
        "condition",
        "Alzheimer disease",
        ("阿尔茨海默病", "阿尔茨海默症", "alzheimer disease", "alzheimer's disease"),
        ('"Alzheimer Disease"[MeSH Terms]', '"Alzheimer disease"[Title/Abstract]'),
    ),
    _ConceptRule(
        "condition",
        "Parkinson disease",
        ("帕金森病", "parkinson disease", "parkinson's disease"),
        ('"Parkinson Disease"[MeSH Terms]', '"Parkinson disease"[Title/Abstract]'),
    ),
    _ConceptRule(
        "condition",
        "Breast Cancer",
        ("乳腺癌", "乳癌", "breast cancer"),
        ('"Breast Neoplasms"[MeSH Terms]', '"breast cancer"[Title/Abstract]'),
    ),
    _ConceptRule(
        "condition",
        "Lung Cancer",
        ("肺癌", "lung cancer"),
        ('"Lung Neoplasms"[MeSH Terms]', '"lung cancer"[Title/Abstract]'),
    ),
    _ConceptRule(
        "condition",
        "Rare Disease",
        ("罕见病", "rare disease", "rare diseases"),
        ('"Rare Diseases"[MeSH Terms]', '"rare disease"[Title/Abstract]'),
    ),
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

_GENERIC_ENGLISH_DISEASE = re.compile(
    r"\b([A-Z][A-Za-z0-9-]{2,}(?:\s+[A-Za-z0-9-]{2,}){0,4}\s+"
    r"(?:disease|syndrome|cancer|carcinoma|leukemia|lymphoma|disorder))\b",
    re.IGNORECASE,
)
_ENGLISH_WORD = re.compile(r"\b[A-Za-z][A-Za-z-]{2,}\b")
_ENGLISH_DISEASE_MARKERS = {
    "disease",
    "syndrome",
    "cancer",
    "carcinoma",
    "leukemia",
    "lymphoma",
    "disorder",
}
_ENGLISH_DISEASE_CONTEXT_WORDS = {
    "a",
    "about",
    "after",
    "an",
    "and",
    "are",
    "case",
    "cases",
    "cause",
    "causes",
    "caused",
    "causing",
    "diagnosed",
    "diagnosis",
    "does",
    "for",
    "from",
    "had",
    "has",
    "have",
    "history",
    "in",
    "is",
    "known",
    "new",
    "of",
    "on",
    "patient",
    "patients",
    "person",
    "reported",
    "research",
    "study",
    "suffered",
    "suffering",
    "the",
    "this",
    "to",
    "what",
    "with",
}
_EXPLICIT_CJK_DISEASE = re.compile(
    r"(?:患有|罹患|患(?!者)|得了|确诊(?:为|是)?|诊断(?:为|是)?|"
    r"病例(?:为|是)?|关于|有关|针对)\s*"
    r"(?P<term>[\u4e00-\u9fff]{2,12}(?:病|症|癌|炎|综合征))"
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
    date_from: date | None = None,
    date_to: date | None = None,
    study_types: list[str] | None = None,
    sort: LiteratureSort = "relevance",
    max_results: int = 20,
    provider: str = "pubmed",
) -> LiteratureQuery:
    """Extract safe concepts and return the exact query shown for confirmation."""
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
    concepts = _extract_concepts(sanitized_question)
    if not concepts:
        raise LiteratureQueryError(
            "No medical concepts could be identified in the question.",
            code="literature_no_medical_concepts",
        )

    normalized_types = _normalize_study_types(study_types or [])
    clauses = [_concept_clause(concept) for concept in concepts]
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
    concepts: list[DetectedConcept] = []
    seen: set[str] = set()
    occupied_spans: list[tuple[int, int]] = []

    for rule in sorted(_CONCEPT_RULES, key=lambda item: max(map(len, item.aliases)), reverse=True):
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
                    )
                )
                seen.add(rule.normalized)
                occupied_spans.append((match.start(), match.end()))
                break

    for pattern in (_GENERIC_ENGLISH_DISEASE, _EXPLICIT_CJK_DISEASE):
        for match in pattern.finditer(question):
            if pattern is _EXPLICIT_CJK_DISEASE:
                raw_value = clean_text(match.group("term"))
                term_start = match.start("term")
                term_end = match.end("term")
            else:
                raw_value = clean_text(match.group(0))
                term_start = match.start()
                term_end = match.end()
            value = (
                _safe_english_disease_term(raw_value)
                if pattern is _GENERIC_ENGLISH_DISEASE
                else _safe_cjk_disease_term(raw_value)
            )
            if not value:
                continue
            normalized = value
            overlaps_known = any(
                term_start < end and term_end > start
                for start, end in occupied_spans
            )
            if (
                overlaps_known
                or normalized.casefold() in seen
                or len(value) > 120
                or any(word.casefold() in _STOP_WORDS for word in value.split())
            ):
                continue
            concepts.append(
                DetectedConcept(
                    type="condition",
                    original=value,
                    normalized=normalized,
                )
            )
            seen.add(normalized.casefold())
            occupied_spans.append((term_start, term_end))

    # A small fallback keeps uncommon but clearly medical questions usable,
    # while still avoiding a raw free-form case narrative in the query.
    if not concepts:
        for token in _ENGLISH_WORD.findall(question):
            normalized = clean_text(token)
            if normalized.casefold() in _STOP_WORDS or len(normalized) < 2:
                continue
            if not _looks_medical(normalized):
                continue
            key = normalized.casefold()
            if key in seen:
                continue
            concepts.append(
                DetectedConcept(type="keyword", original=normalized, normalized=normalized)
            )
            seen.add(key)
            if len(concepts) == 5:
                break

    return concepts[:8]


def _find_alias_match(question: str, rule: _ConceptRule, alias: str) -> re.Match[str] | None:
    """Match English aliases as words so short gene symbols cannot hit substrings."""
    if rule.concept_type == "gene" and alias == "GLA":
        return re.search(r"(?<![A-Za-z0-9])GLA(?![A-Za-z0-9])", question)
    if re.search(r"[A-Za-z]", alias):
        pattern = r"(?<![A-Za-z0-9])" + re.escape(alias) + r"(?![A-Za-z0-9])"
        return re.search(pattern, question, flags=re.IGNORECASE)
    return re.search(re.escape(alias), question)


def _safe_english_disease_term(value: str) -> str | None:
    """Keep a disease phrase, never the narrative that introduced it."""
    tokens = value.split()
    if len(tokens) < 2 or tokens[-1].casefold() not in _ENGLISH_DISEASE_MARKERS:
        return None

    context_index = max(
        (
            index
            for index, token in enumerate(tokens[:-1])
            if token.casefold().strip(".,;:()") in _ENGLISH_DISEASE_CONTEXT_WORDS
        ),
        default=-1,
    )
    if context_index >= 0:
        tokens = tokens[context_index + 1 :]
    elif len(tokens) > 2:
        # Without a narrative boundary, a multi-word free-form match could be
        # a person's name followed by a disease. Prefer no search to leakage.
        if all(token[:1].isupper() and token.isalpha() for token in tokens[:-1]):
            return None
        return None

    if not tokens or any(
        token.casefold().strip(".,;:()") in _ENGLISH_DISEASE_CONTEXT_WORDS
        for token in tokens[:-1]
    ):
        return None
    return clean_text(" ".join(tokens))


def _safe_cjk_disease_term(value: str) -> str | None:
    """Accept only the exact disease term captured after an explicit marker."""
    candidate = clean_text(value)
    if not re.fullmatch(r"[\u4e00-\u9fff]{2,12}(?:病|症|癌|炎|综合征)", candidate):
        return None
    if any(fragment in candidate for fragment in ("的", "患", "罹", "诊断", "确诊", "病例")):
        return None
    return candidate


def _looks_medical(token: str) -> bool:
    lowered = token.casefold()
    return any(
        hint in lowered
        for hint in (
            "disease",
            "syndrome",
            "cancer",
            "tumor",
            "patient",
            "symptom",
            "treatment",
            "therapy",
            "drug",
            "renal",
            "kidney",
            "blood",
            "liver",
            "heart",
            "gene",
            "病",
            "症",
            "癌",
            "炎",
            "治疗",
            "患者",
            "肾",
            "肝",
        )
    )


def _concept_clause(concept: DetectedConcept) -> str:
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
    date_from: date | None,
    date_to: date | None,
    study_types: list[str],
    sort: str,
    max_results: int,
) -> str:
    payload = {
        "provider": provider.strip().lower(),
        "query": normalized_query,
        "date_from": date_from.isoformat() if date_from else None,
        "date_to": date_to.isoformat() if date_to else None,
        "study_types": list(study_types),
        "sort": sort,
        "max_results": max_results,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
