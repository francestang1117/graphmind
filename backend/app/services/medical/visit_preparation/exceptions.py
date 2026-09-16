"""Expected errors for the visit-preparation workflow."""

from __future__ import annotations

from typing import Any


class VisitPreparationError(Exception):
    """An expected failure with a stable API error code."""

    def __init__(
        self,
        message: str,
        *,
        code: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.message = message
        self.code = code
        self.details = details or {}
        super().__init__(message)
