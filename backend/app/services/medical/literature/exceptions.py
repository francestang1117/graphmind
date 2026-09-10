"""Expected errors from the medical literature search boundary."""

from __future__ import annotations


class LiteratureError(Exception):
    """An expected, public-safe literature error."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "literature_search_failed",
        retryable: bool = False,
    ) -> None:
        self.message = message
        self.code = code
        self.retryable = retryable
        super().__init__(message)


class LiteratureConfigurationError(LiteratureError):
    """The server is not configured to contact the literature provider."""


class LiteratureQueryError(LiteratureError):
    """The requested search cannot be represented safely."""


class LiteratureProviderError(LiteratureError):
    """The external provider did not return usable data."""
