"""Shared confirmation checks for the external literature query boundary."""

from __future__ import annotations

from app.services.medical.literature.exceptions import LiteratureQueryError
from app.services.medical.literature.models import LiteratureQuery


def confirm_literature_query(
    query: LiteratureQuery,
    *,
    external_search_confirmed: bool,
    query_fingerprint: str | None,
) -> None:
    """Validate the same release conditions used by the HTTP endpoint."""
    if query.resolution_status != "ready":
        raise LiteratureQueryError(
            "Choose a disease concept before starting the external search.",
            code="literature_concept_confirmation_required",
        )
    if not external_search_confirmed:
        raise LiteratureQueryError(
            "Confirm the PubMed query before starting the external search.",
            code="external_search_confirmation_required",
        )
    if query_fingerprint != query.query_hash:
        raise LiteratureQueryError(
            "The literature query changed. Review and confirm it again.",
            code="external_search_query_changed",
        )
