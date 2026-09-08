"""Versioned prompts shared by providers and validation retries."""

from __future__ import annotations

import json
from typing import Any

from app.services.medical.ai.context_builder import AnalysisContext


def build_prompt(context: AnalysisContext, *, schema_version: str = "medical-insights-v1") -> str:
    """Build the initial request without asking the provider to invent facts."""
    return _instructions(schema_version) + "\n\nSOURCE EVIDENCE\n" + context.render()


def build_repair_prompt(
    context: AnalysisContext,
    invalid_output: Any,
    errors: list[str],
    *,
    schema_version: str = "medical-insights-v1",
) -> str:
    """Ask for a corrected JSON object after one failed validation pass."""
    return (
        _instructions(schema_version)
        + "\n\nThe previous output failed these checks:\n"
        + "\n".join(f"- {error}" for error in errors)
        + "\n\nPrevious output:\n"
        + json.dumps(invalid_output, ensure_ascii=False, default=str)
        + "\n\nSOURCE EVIDENCE\n"
        + context.render()
    )


def _instructions(schema_version: str) -> str:
    return f"""You are summarizing one medical document for a general reader.
Return one JSON object that follows the MedicalInsightReport schema.
Schema version: {schema_version}

Rules:
- Use only the supplied SOURCE EVIDENCE.
- Cite source blocks with their exact Evidence IDs, such as EVIDENCE_003.
- Every overview, finding, limitation, term explanation, and meaning statement
  needs at least one Evidence ID. If the source does not say something, omit it
  or state that it was not found; do not fill it from general knowledge.
- Keep direct statements, summaries, inferences, and uncertainty distinct.
- Do not diagnose the reader, prescribe treatment, adjust a dose, or tell a
  person to start or stop a medicine.
- Explain what the document does not establish when that is supported by the
  document's design or limitations.
- Do not use References as evidence for the document's own results.
- Return JSON only. Do not add Markdown fences or extra keys."""
