"""Provider interface for medical literature sources."""

from __future__ import annotations

from typing import Protocol

from app.services.medical.literature.models import LiteratureQuery, LiteratureSearchPage


class LiteratureProvider(Protocol):
    async def search(self, query: LiteratureQuery) -> LiteratureSearchPage:
        """Search the provider and return normalized metadata."""

