"""Check generated text for a few unsafe medical claims."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.services.medical.ai.models import MedicalInsightReport


@dataclass
class SafetyValidation:
    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=lambda: ["not_medical_advice"])


_PERSONAL_DIAGNOSIS = re.compile(
    r"\b(?:you have|you likely have|this proves you have|diagnose you)\b",
    re.I,
)
_TREATMENT_COMMAND = re.compile(
    r"\b(?:you should|stop|start|change|adjust|increase|decrease)\s+"
    r"(?:your|the)?\s*(?:medication|medicine|dose|dosage|treatment|drug)\b",
    re.I,
)


def validate_safety(report: MedicalInsightReport) -> SafetyValidation:
    """Reject direct diagnosis and treatment instructions before persistence."""
    text = _report_text(report)
    errors: list[str] = []
    if _PERSONAL_DIAGNOSIS.search(text):
        errors.append("report contains a personalized diagnosis")
    if _TREATMENT_COMMAND.search(text):
        errors.append("report contains a treatment or medication instruction")
    return SafetyValidation(valid=not errors, errors=errors)


def _report_text(report: MedicalInsightReport) -> str:
    parts = [
        report.overview.summary,
        *(item.statement for item in report.key_findings),
        *(item.plain_explanation for item in report.key_findings),
        *(item.statement for item in report.limitations),
        *(item.plain_explanation for item in report.limitations),
        *(item.statement for item in report.what_it_means),
        *(item.plain_explanation for item in report.what_it_means),
        *(item.statement for item in report.what_it_does_not_mean),
        *(item.plain_explanation for item in report.what_it_does_not_mean),
        *(item.explanation for item in report.medical_terms),
    ]
    return "\n".join(parts)
