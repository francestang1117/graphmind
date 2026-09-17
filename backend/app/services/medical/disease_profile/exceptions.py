"""Expected errors for disease profile reads and document links."""

from __future__ import annotations

from typing import Any


class DiseaseProfileError(Exception):
    """A public-safe failure with a stable API code and status."""

    def __init__(
        self,
        message: str,
        *,
        code: str,
        status_code: int = 503,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.message = message
        self.code = code
        self.status_code = status_code
        self.details = details or {}
        super().__init__(message)
