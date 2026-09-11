"""Validate controlled PubMed clauses before they enter a data package."""

from __future__ import annotations

import re

from app.services.medical.terminology.models import DiseaseConcept


_PUBMED_TERM = re.compile(
    r'^(?:"[^"\r\n]{1,200}"|[A-Za-z][A-Za-z0-9-]{0,199})'
    r'\[(?:MeSH Terms|Title/Abstract)\]$'
)


def validate_pubmed_term(value: object) -> str:
    """Accept only the two controlled field forms used by the query builder."""
    term = str(value or "").strip()
    if not _PUBMED_TERM.fullmatch(term):
        raise ValueError("invalid PubMed term template")
    return term


def pubmed_terms_for_concept(concept: DiseaseConcept) -> tuple[str, ...]:
    """Return validated clauses from a trusted ontology record."""
    return tuple(validate_pubmed_term(term) for term in concept.pubmed_terms)
