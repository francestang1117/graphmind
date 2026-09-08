"""Errors raised while building or checking a medical insight report."""

from __future__ import annotations

from typing import Any


class MedicalInsightError(RuntimeError):
    """A failure that belongs to the insight run, not the source document."""

    code = "medical_insight_failed"

    def __init__(self, message: str, *, code: str | None = None, details: dict[str, Any] | None = None):
        self.code = code or self.code
        self.details = details or {}
        super().__init__(message)


class ProviderUnavailable(MedicalInsightError):
    code = "provider_unavailable"


class MedicalInsightValidationError(MedicalInsightError):
    code = "failed_validation"

    def __init__(self, message: str, *, errors: list[str] | None = None):
        self.errors = errors or []
        super().__init__(message, details={"errors": self.errors})
