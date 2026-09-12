"""Explainable local matching between report findings and saved PubMed articles."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Iterable, Mapping

from app.services.medical.evidence_matching.models import (
    FindingMatchResult,
    LiteratureMatchResult,
    MatchFeature,
    MatchableFinding,
    StudyCard,
)
from app.services.medical.evidence_matching.study_card_builder import StudyCardBuilder, build_study_card
from app.services.medical.terminology.normalizer import normalize_terminology_text


EXCLUDED_RETRACTION_STATUSES = {"retracted", "retraction_notice"}
WARNED_RETRACTION_STATUSES = {"expression_of_concern", "corrected", "correction_notice", "unknown"}

_SENTENCE_END = re.compile(r"[.!?。！？](?:\s+|$)")
_ASCII_TERM = re.compile(r"[A-Za-z0-9]")


@dataclass(frozen=True)
class _ArticleMatch:
    score: int
    specificity: str
    terms: tuple[str, ...]
    features: tuple[MatchFeature, ...]
    quote: str | None
    quote_start: int | None
    quote_end: int | None


class LiteratureCandidateMatcher:
    """Match at most a bounded local PubMed result set without external calls."""

    def __init__(
        self,
        *,
        min_score: int = 40,
        max_articles: int = 50,
        max_per_finding: int = 5,
        quote_length: int = 600,
    ) -> None:
        self.min_score = max(0, min(int(min_score), 100))
        self.max_articles = max(1, min(int(max_articles or 1), 50))
        self.max_per_finding = max(1, min(int(max_per_finding or 1), 5))
        self.card_builder = StudyCardBuilder(quote_length=quote_length)

    def match(
        self,
        findings: Iterable[MatchableFinding],
        articles: Iterable[Any],
    ) -> LiteratureMatchResult:
        excluded: dict[str, int] = {}
        eligible: list[tuple[Any, int]] = []
        ranked_articles = [
            (article, _provider_rank(article, index))
            for index, article in enumerate(list(articles), start=1)
        ]
        # Provider rank is part of the persisted input. Sort before applying
        # the hard cap so a caller cannot change the candidate set by merely
        # reordering an otherwise identical saved result list.
        ranked_articles.sort(
            key=lambda item: (
                item[1],
                _article_id_sort_key(item[0]),
            )
        )
        for article, rank in ranked_articles[: self.max_articles]:
            status = str(_value(article, "retraction_status") or "unknown").strip().lower()
            if status in EXCLUDED_RETRACTION_STATUSES:
                excluded[status] = excluded.get(status, 0) + 1
                continue
            if not str(_value(article, "external_id") or _value(article, "pmid") or "").strip():
                excluded["missing_metadata"] = excluded.get("missing_metadata", 0) + 1
                continue
            if not str(_value(article, "title") or "").strip():
                excluded["missing_metadata"] = excluded.get("missing_metadata", 0) + 1
                continue
            eligible.append((article, rank))

        result_findings: list[FindingMatchResult] = []
        for finding in findings:
            if not _has_match_terms(finding):
                result_findings.append(
                    FindingMatchResult(finding=finding, match_status="insufficient_terms")
                )
                continue
            candidates: list[tuple[Any, int, _ArticleMatch]] = []
            for article, rank in eligible:
                matched = self._score(finding, article, rank)
                if matched is not None:
                    candidates.append((article, rank, matched))
            candidates.sort(key=lambda item: _candidate_sort_key(item[0], item[1], item[2]))
            cards: list[StudyCard] = []
            for article, _rank, matched in candidates[: self.max_per_finding]:
                cards.append(
                    self.card_builder.build(
                        article,
                        relevance_score=matched.score,
                        match_specificity=matched.specificity,
                        matched_terms=matched.terms,
                        match_reasons=[feature.explanation for feature in matched.features],
                        match_features=matched.features,
                        abstract_quote=matched.quote,
                        abstract_character_start=matched.quote_start,
                        abstract_character_end=matched.quote_end,
                    )
                )
            status = "matched" if cards else "no_candidates"
            if cards and all(card.match_specificity == "condition_only" for card in cards):
                status = "condition_only"
            result_findings.append(
                FindingMatchResult(
                    finding=finding,
                    match_status=status,
                    candidates=cards,
                )
            )

        match_count = sum(len(item.candidates) for item in result_findings)
        empty_reason = "no_eligible_articles" if not eligible else ""
        warnings = []
        if excluded.get("retracted") or excluded.get("retraction_notice"):
            warnings.append("Retracted PubMed articles were excluded from the candidate list.")
        if excluded.get("missing_metadata"):
            warnings.append("Some PubMed records were excluded because required metadata was missing.")
        return LiteratureMatchResult(
            findings=result_findings,
            excluded_articles=excluded,
            warnings=warnings,
            empty_reason=empty_reason,
            article_count=len(eligible),
            match_count=match_count,
        )

    def _score(self, finding: MatchableFinding, article: Any, provider_rank: int) -> _ArticleMatch | None:
        title = str(_value(article, "title") or "")
        abstract = str(_value(article, "abstract") or "")
        mesh_terms = _list_value(article, "mesh_terms")
        features: list[MatchFeature] = []
        matched_terms: list[str] = []

        mesh_hits = _term_hits(mesh_terms, finding.condition_terms)
        if mesh_hits:
            features.append(
                MatchFeature(
                    feature="mesh_condition_match",
                    score=35,
                    matched_values=mesh_hits,
                    explanation="The article's MeSH terms include the same controlled condition.",
                )
            )
            matched_terms.extend(mesh_hits)

        title_condition_hits = _term_hits(title, finding.condition_terms)
        if title_condition_hits:
            features.append(
                MatchFeature(
                    feature="title_condition_match",
                    score=25,
                    matched_values=title_condition_hits,
                    explanation="The controlled condition appears in the article title.",
                )
            )
            matched_terms.extend(title_condition_hits)

        abstract_condition_hits = _term_hits(abstract, finding.condition_terms)
        if abstract_condition_hits and not mesh_hits and not title_condition_hits:
            features.append(
                MatchFeature(
                    feature="abstract_condition_match",
                    score=15,
                    matched_values=abstract_condition_hits,
                    explanation="The controlled condition appears in the article abstract.",
                )
            )
            matched_terms.extend(abstract_condition_hits)

        non_condition_phrases = [
            phrase for phrase in finding.phrases if not _matches_any_term(phrase, finding.condition_terms)
        ]
        title_phrase_hits = _term_hits(title, non_condition_phrases)
        if title_phrase_hits:
            features.append(
                MatchFeature(
                    feature="title_finding_phrase",
                    score=20,
                    matched_values=title_phrase_hits,
                    explanation="A phrase from the finding appears in the article title.",
                )
            )
            matched_terms.extend(title_phrase_hits)

        title_keyword_hits = _term_hits(title, finding.keywords)
        if title_keyword_hits:
            score = min(15, len(title_keyword_hits) * 5)
            features.append(
                MatchFeature(
                    feature="title_keyword_overlap",
                    score=score,
                    matched_values=title_keyword_hits,
                    explanation="Finding keywords overlap with the article title.",
                )
            )
            matched_terms.extend(title_keyword_hits)

        abstract_keyword_hits = _term_hits(abstract, finding.keywords)
        if abstract_keyword_hits:
            score = min(15, len(abstract_keyword_hits) * 3)
            features.append(
                MatchFeature(
                    feature="abstract_keyword_overlap",
                    score=score,
                    matched_values=abstract_keyword_hits,
                    explanation="Finding keywords overlap with the article abstract.",
                )
            )
            matched_terms.extend(abstract_keyword_hits)

        biomedical_hits = _term_hits(
            f"{title} {abstract} {' '.join(mesh_terms)}",
            finding.biomedical_terms,
        )
        if biomedical_hits:
            features.append(
                MatchFeature(
                    feature="controlled_biomedical_match",
                    score=20,
                    matched_values=biomedical_hits,
                    explanation="A controlled gene, drug, or biomedical term overlaps the article metadata.",
                )
            )
            matched_terms.extend(biomedical_hits)

        rank_bonus = max(0, min(5, 6 - max(1, int(provider_rank))))
        if rank_bonus:
            features.append(
                MatchFeature(
                    feature="provider_rank_bonus",
                    score=rank_bonus,
                    matched_values=[str(provider_rank)],
                    explanation="The article was returned near the top of the PubMed result ranking.",
                )
            )

        condition_found = bool(mesh_hits or title_condition_hits or abstract_condition_hits)
        specific_features = [
            feature
            for feature in features
            if feature.feature
            not in {"mesh_condition_match", "title_condition_match", "abstract_condition_match", "provider_rank_bonus"}
        ]
        score = min(100, sum(feature.score for feature in features))
        if not condition_found and not specific_features:
            return None
        if not specific_features:
            specificity = "condition_only"
        elif score >= self.min_score:
            specificity = "finding_specific"
        elif condition_found:
            return None
        else:
            return None

        preferred_quote_terms = _quote_terms(features)
        quote, quote_start, quote_end = locate_abstract_quote(
            abstract,
            preferred_quote_terms,
            max_length=self.card_builder.quote_length,
        )
        return _ArticleMatch(
            score=score,
            specificity=specificity,
            terms=tuple(_dedupe(matched_terms)),
            features=tuple(features),
            quote=quote,
            quote_start=quote_start,
            quote_end=quote_end,
        )


def match_articles(
    findings: Iterable[MatchableFinding],
    articles: Iterable[Any],
    *,
    min_score: int = 40,
    max_articles: int = 50,
    max_per_finding: int = 5,
    quote_length: int = 600,
) -> LiteratureMatchResult:
    """Functional wrapper for deterministic unit and integration tests."""
    return LiteratureCandidateMatcher(
        min_score=min_score,
        max_articles=max_articles,
        max_per_finding=max_per_finding,
        quote_length=quote_length,
    ).match(findings, articles)


def locate_abstract_quote(
    abstract: str,
    terms: Iterable[str],
    *,
    max_length: int = 600,
) -> tuple[str | None, int | None, int | None]:
    """Return an unchanged abstract slice and its Python character offsets."""
    text = str(abstract or "")
    limit = max(1, min(int(max_length or 1), 600))
    for term in terms:
        candidate = str(term or "").strip()
        if not candidate:
            continue
        occurrence = re.search(re.escape(candidate), text, flags=re.IGNORECASE)
        if occurrence:
            # ``terms`` is ordered by feature weight. Pick the first term
            # that occurs so the quote follows the strongest explanation,
            # even when a lower-weight term appears earlier in the abstract.
            occurrence_start = occurrence.start()
            occurrence_end = occurrence.end()
            break
    else:
        return None, None, None
    sentence_start = 0
    sentence_end = len(text)
    for boundary in _SENTENCE_END.finditer(text):
        if boundary.end() <= occurrence_start:
            sentence_start = boundary.end()
        elif boundary.start() < occurrence_end:
            continue
        else:
            sentence_end = boundary.end()
            break
    while sentence_start < sentence_end and text[sentence_start].isspace():
        sentence_start += 1
    while sentence_end > sentence_start and text[sentence_end - 1].isspace():
        sentence_end -= 1
    if sentence_end - sentence_start <= limit:
        return text[sentence_start:sentence_end], sentence_start, sentence_end

    window_start = max(sentence_start, occurrence_start - limit // 3)
    window_end = min(sentence_end, window_start + limit)
    if window_end - window_start < limit:
        window_start = max(sentence_start, window_end - limit)
    return text[window_start:window_end], window_start, window_end


def _quote_terms(features: Iterable[MatchFeature]) -> list[str]:
    priority = {
        "title_finding_phrase": 0,
        "controlled_biomedical_match": 1,
        "abstract_keyword_overlap": 2,
        "title_keyword_overlap": 3,
        "abstract_condition_match": 4,
        "title_condition_match": 5,
        "mesh_condition_match": 6,
    }
    result: list[str] = []
    for feature in sorted(features, key=lambda item: priority.get(item.feature, 99)):
        result.extend(feature.matched_values)
    return _dedupe(result)


def _candidate_sort_key(article: Any, rank: int, matched: _ArticleMatch) -> tuple[Any, ...]:
    return (
        0 if matched.specificity == "finding_specific" else 1,
        -matched.score,
        0 if any(feature.feature.startswith("title_") for feature in matched.features) else 1,
        rank,
        _article_id_sort_key(article),
    )


def _has_match_terms(finding: MatchableFinding) -> bool:
    return bool(finding.condition_terms or finding.biomedical_terms or finding.keywords or finding.phrases)


def _term_hits(text: str | Iterable[str], terms: Iterable[str]) -> list[str]:
    values = [text] if isinstance(text, str) else list(text)
    haystack = " ".join(str(item or "") for item in values)
    hits: list[str] = []
    for term in terms:
        candidate = str(term or "").strip()
        if candidate and _contains_term(haystack, candidate) and candidate not in hits:
            hits.append(candidate)
    return hits


def _matches_any_term(value: str, terms: Iterable[str]) -> bool:
    return any(_contains_term(value, term) for term in terms if str(term or "").strip())


def _contains_term(text: str, term: str) -> bool:
    normalized_text = normalize_terminology_text(text)
    normalized_term = normalize_terminology_text(term)
    if not normalized_text or not normalized_term:
        return False
    if _ASCII_TERM.search(normalized_term):
        pattern = r"(?<![A-Za-z0-9])" + re.escape(normalized_term) + r"(?![A-Za-z0-9])"
        return re.search(pattern, normalized_text, flags=re.IGNORECASE) is not None
    return normalized_term in normalized_text


def _value(article: Any, field: str) -> Any:
    if isinstance(article, Mapping):
        return article.get(field)
    return getattr(article, field, None)


def _provider_rank(article: Any, fallback: int) -> int:
    try:
        value = int(_value(article, "provider_rank") or fallback)
    except (TypeError, ValueError):
        value = fallback
    return max(1, value)


def _article_id_sort_key(article: Any) -> tuple[int, int | str]:
    value = str(_value(article, "external_id") or _value(article, "pmid") or "").strip()
    if value.isdigit():
        return 0, int(value)
    return 1, value


def _list_value(article: Any, field: str) -> list[str]:
    value = _value(article, field)
    if not isinstance(value, (list, tuple)):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _dedupe(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value or "").strip()
        if item and item.casefold() not in seen:
            seen.add(item.casefold())
            result.append(item)
    return result
