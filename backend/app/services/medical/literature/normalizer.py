"""Normalization and stable hashing for PubMed metadata."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Iterable

from app.services.medical.literature.models import LiteratureArticle


_WHITESPACE = re.compile(r"\s+")


def clean_text(value: object) -> str:
    """Collapse layout whitespace without changing the words themselves."""
    return _WHITESPACE.sub(" ", str(value or "")).strip()


def normalize_doi(value: object) -> str | None:
    """Keep a DOI stable across URL, prefix, and case variants."""
    doi = clean_text(value).lower()
    if not doi:
        return None
    doi = re.sub(r"^https?://(dx\.)?doi\.org/", "", doi)
    doi = re.sub(r"^doi:\s*", "", doi)
    return doi or None


def normalize_date_parts(year: object, month: object = None, day: object = None) -> tuple[str | None, int | None]:
    """Return only date precision present in PubMed; never invent a day."""
    year_text = clean_text(year)
    match = re.search(r"\b(\d{4})\b", year_text)
    if not match:
        return None, None
    year_number = int(match.group(1))
    month_number = _month_number(month)
    day_number = _number(day)
    if month_number and day_number and 1 <= day_number <= 31:
        return f"{year_number:04d}-{month_number:02d}-{day_number:02d}", year_number
    if month_number:
        return f"{year_number:04d}-{month_number:02d}", year_number
    return str(year_number), year_number


def metadata_hash(article: LiteratureArticle | dict[str, object]) -> str:
    """Hash the public metadata, excluding fetch time and internal IDs."""
    if isinstance(article, LiteratureArticle):
        values = article.model_dump()
    else:
        values = dict(article)
    values.pop("fetched_at", None)
    values.pop("metadata_hash", None)
    encoded = json.dumps(values, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def deduplicate_articles(articles: Iterable[LiteratureArticle]) -> list[LiteratureArticle]:
    """Deduplicate by PMID first, then DOI while preserving provider order."""
    result: list[LiteratureArticle] = []
    seen_pmids: set[str] = set()
    seen_dois: set[str] = set()
    for article in articles:
        pmid = article.external_id.strip()
        doi = (article.doi or "").strip().lower()
        if not pmid or pmid in seen_pmids or (doi and doi in seen_dois):
            continue
        seen_pmids.add(pmid)
        if doi:
            seen_dois.add(doi)
        result.append(article)
    return result


def _month_number(value: object) -> int | None:
    text = clean_text(value).lower().rstrip(".")
    if not text:
        return None
    if text.isdigit():
        number = int(text)
        return number if 1 <= number <= 12 else None
    months = {
        "jan": 1,
        "january": 1,
        "feb": 2,
        "february": 2,
        "mar": 3,
        "march": 3,
        "apr": 4,
        "april": 4,
        "may": 5,
        "jun": 6,
        "june": 6,
        "jul": 7,
        "july": 7,
        "aug": 8,
        "august": 8,
        "sep": 9,
        "sept": 9,
        "september": 9,
        "oct": 10,
        "october": 10,
        "nov": 11,
        "november": 11,
        "dec": 12,
        "december": 12,
    }
    return months.get(text)


def _number(value: object) -> int | None:
    text = clean_text(value)
    return int(text) if text.isdigit() else None
