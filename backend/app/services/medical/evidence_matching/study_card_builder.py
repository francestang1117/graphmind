"""Build transparent study cards from PubMed-provided metadata only."""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from app.services.medical.evidence_matching.models import MatchFeature, StudyCard


RELEVANCE_WARNING = "This is a potentially relevant research article."
NO_PROOF_WARNING = "Relevance does not mean that the article proves the finding."


def build_study_card(
    article: Any,
    *,
    relevance_score: int,
    match_specificity: str,
    matched_terms: Iterable[str] = (),
    match_reasons: Iterable[str] = (),
    match_features: Iterable[MatchFeature | Mapping[str, Any]] = (),
    abstract_quote: str | None = None,
    abstract_character_start: int | None = None,
    abstract_character_end: int | None = None,
    quote_length: int = 600,
) -> StudyCard:
    """Create one card without inferring efficacy, phase, or study quality."""
    types = _list_value(article, "publication_types")
    category = classify_study_category(types)
    phase = development_phase(types)
    pmid = str(_value(article, "external_id") or _value(article, "pmid") or "").strip()
    if not pmid:
        raise ValueError("a PubMed article must have a PMID")
    source_url = str(_value(article, "source_url") or "").strip()
    if not source_url:
        source_url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"

    warnings = [RELEVANCE_WARNING, NO_PROOF_WARNING]
    retraction_status = str(_value(article, "retraction_status") or "unknown").strip().lower()
    if retraction_status == "expression_of_concern":
        warnings.append("PubMed marks this article with an expression of concern.")
    elif retraction_status in {"corrected", "correction_notice"}:
        warnings.append("PubMed indicates that this article has a correction notice.")
    elif retraction_status == "unknown":
        warnings.append("The article's publication status is unknown.")
    if not str(_value(article, "abstract") or "").strip():
        warnings.append("No PubMed abstract is available for this article.")

    normalized_features = [
        item if isinstance(item, MatchFeature) else MatchFeature.model_validate(item)
        for item in match_features
    ]
    quote = abstract_quote
    if quote is not None:
        quote = quote[: max(1, min(int(quote_length or 1), 600))]

    return StudyCard(
        article_id=str(_value(article, "id") or pmid),
        source="pubmed",
        pmid=pmid,
        doi=_optional_value(article, "doi"),
        pmcid=_optional_value(article, "pmcid"),
        title=str(_value(article, "title") or ""),
        journal=str(_value(article, "journal") or ""),
        publication_year=_int_value(article, "publication_year"),
        publication_types=types,
        study_category=category,
        development_phase=phase,
        abstract_available=bool(str(_value(article, "abstract") or "").strip()),
        relevance_score=max(0, min(int(relevance_score), 100)),
        match_specificity=match_specificity,
        matched_terms=_dedupe_strings(matched_terms, limit=30),
        match_reasons=_dedupe_strings(match_reasons, limit=20),
        match_features=normalized_features[:20],
        abstract_quote=quote,
        abstract_character_start=abstract_character_start,
        abstract_character_end=abstract_character_end,
        retraction_status=retraction_status or "unknown",
        source_url=source_url,
        warnings=_dedupe_strings(warnings, limit=20),
    )


class StudyCardBuilder:
    """Small object wrapper for callers that keep matching configuration."""

    def __init__(self, *, quote_length: int = 600) -> None:
        self.quote_length = max(1, min(int(quote_length or 1), 600))

    def build(self, article: Any, **kwargs: Any) -> StudyCard:
        return build_study_card(article, quote_length=self.quote_length, **kwargs)


def classify_study_category(publication_types: Iterable[str]) -> str:
    """Classify only from the publication type labels returned by PubMed."""
    values = _normalized_types(publication_types)
    if _contains_any(values, "practice guideline", "guideline", "clinical practice guideline"):
        return "guideline"
    if _contains_any(values, "systematic review", "scoping review"):
        return "systematic_review"
    if _contains_any(values, "meta-analysis", "meta analysis"):
        return "meta_analysis"
    if _contains_any(values, "randomized controlled trial", "randomised controlled trial"):
        return "randomized_controlled_trial"
    if _contains_any(values, "phase iii", "phase 3"):
        return "clinical_trial_phase_3"
    if _contains_any(values, "phase ii", "phase 2"):
        return "clinical_trial_phase_2"
    if _contains_any(values, "phase i", "phase 1"):
        return "clinical_trial_phase_1"
    if _contains_any(values, "clinical trial", "clinical study"):
        return "clinical_trial"
    if _contains_any(
        values,
        "observational study",
        "cohort study",
        "case-control study",
        "cross-sectional study",
    ):
        return "observational_study"
    if _contains_any(values, "case report", "case series"):
        return "case_report"
    if _contains_any(values, "in vitro", "animal experimentation", "animal study", "preclinical"):
        return "preclinical"
    return "unknown"


def development_phase(publication_types: Iterable[str]) -> str:
    """Return a phase only when PubMed explicitly supplies one."""
    values = _normalized_types(publication_types)
    if _contains_any(values, "phase iii", "phase 3"):
        return "phase_3"
    if _contains_any(values, "phase ii", "phase 2"):
        return "phase_2"
    if _contains_any(values, "phase i", "phase 1"):
        return "phase_1"
    return "not_reported"


def _normalized_types(values: Iterable[str]) -> list[str]:
    return [str(value or "").strip().casefold() for value in values if str(value or "").strip()]


def _contains_any(values: Iterable[str], *needles: str) -> bool:
    return any(needle in value for value in values for needle in needles)


def _value(article: Any, field: str) -> Any:
    if isinstance(article, Mapping):
        return article.get(field)
    return getattr(article, field, None)


def _optional_value(article: Any, field: str) -> str | None:
    value = str(_value(article, field) or "").strip()
    return value or None


def _int_value(article: Any, field: str) -> int | None:
    value = _value(article, field)
    try:
        return int(value) if value is not None and str(value).strip() else None
    except (TypeError, ValueError):
        return None


def _list_value(article: Any, field: str) -> list[str]:
    value = _value(article, field)
    if not isinstance(value, (list, tuple)):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _dedupe_strings(values: Iterable[str], *, limit: int) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value or "").strip()
        if item and item not in seen:
            seen.add(item)
            result.append(item)
            if len(result) >= limit:
                break
    return result

