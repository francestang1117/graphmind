"""Public-safe errors raised by the literature matching workflow."""

from __future__ import annotations


class LiteratureMatchingError(RuntimeError):
    """An expected matching or persistence failure with a stable API code."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code

