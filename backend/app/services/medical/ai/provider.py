"""Provider boundary for medical insight generation.

The local provider keeps development and tests deterministic. A remote model
can be added later without changing the report or citation contracts.
"""

from __future__ import annotations

import copy
import re
import time
from collections.abc import Callable
from typing import Any, Protocol

from app.services.medical.ai.context_builder import AnalysisContext, EvidenceItem
from app.services.medical.ai.exceptions import MedicalInsightError, ProviderUnavailable
from app.services.medical.ai.models import MedicalInsightReport


class MedicalAIProvider(Protocol):
    name: str
    model_name: str

    def generate(self, prompt: str, context: AnalysisContext) -> Any:
        """Return a JSON-compatible report candidate."""


class ExtractiveMedicalAIProvider:
    """Create a conservative local report from selected source passages."""

    name = "extractive"

    def __init__(self, model_name: str = "extractive-v1") -> None:
        self.model_name = model_name

    def generate(self, _prompt: str, context: AnalysisContext) -> dict[str, Any]:
        evidence = context.evidence
        overview_item = _first_of(
            evidence,
            "abstract",
            "scope",
            "recommendations",
            "evidence",
            "results",
            "conclusion",
            "introduction",
        ) or (evidence[0] if evidence else None)
        summary = _summary(overview_item.text if overview_item else "")
        if not summary:
            summary = "The document contains no extractable passage for a summary."

        findings = []
        for item in _take_distinct(
            evidence,
            {
                "results",
                "recommendations",
                "evidence",
                "contraindications",
                "scope",
                "conclusion",
                "abstract",
            },
            limit=3,
        ):
            statement = _summary(item.text)
            if not statement:
                continue
            findings.append(
                _finding(
                    f"finding_{len(findings) + 1:03d}",
                    statement,
                    f"This is reported in the document's {item.section_type} section.",
                    item,
                    interpretation_type="direct_statement",
                )
            )

        if not findings and overview_item:
            findings.append(
                _finding(
                    "finding_001",
                    summary,
                    "This is the clearest extractable statement in the document.",
                    overview_item,
                    interpretation_type="summary",
                )
            )

        limitations = [
            _finding(
                f"limitation_{index:03d}",
                _summary(item.text),
                "This limitation is stated in the source document.",
                item,
                interpretation_type="direct_statement",
            )
            for index, item in enumerate(
                _take_distinct(evidence, {"limitations"}, limit=2),
                start=1,
            )
            if _summary(item.text)
        ]

        meaning_item = _first_of(
            evidence,
            "recommendations",
            "results",
            "evidence",
            "conclusion",
        )
        meanings = []
        if meaning_item:
            meanings.append(
                _finding(
                    "meaning_001",
                    f"Within this document, the reported result is: {_summary(meaning_item.text)}",
                    "This is a plain-language restatement of the cited passage, not a personal medical recommendation.",
                    meaning_item,
                    interpretation_type="summary",
                )
            )

        does_not_mean = []
        if limitations and meaning_item:
            does_not_mean.append(
                _finding(
                    "boundary_001",
                    "The document's findings should be read within the study population, methods, and limitations described by the authors.",
                    "The source includes limitations, so the result should not be treated as proof that it applies to every patient.",
                    _item_for_finding(limitations[0], evidence),
                    interpretation_type="inference",
                )
            )

        warnings = ["not_medical_advice", *context.warnings]
        return {
            "schema_version": "medical-insights-v2",
            "document_kind": context.document_kind,
            "language": context.language,
            "overview": {
                "title": context.title,
                "summary": summary,
                "study_type": _study_type(context.document_kind),
                "evidence_ids": [overview_item.evidence_id] if overview_item else [],
            },
            "study_methods": {},
            "key_findings": findings,
            "limitations": limitations,
            "medical_terms": [],
            "what_it_means": meanings,
            "what_it_does_not_mean": does_not_mean,
            "applicability": [],
            "future_research": [],
            "questions_for_professional": [
                "Which people were included in this document, and who was not included?",
                "How strong are the reported findings and their limitations?",
            ],
            "coverage": _coverage(context),
            "warnings": warnings,
        }


class OpenAIMedicalAIProvider:
    """Generate a schema-constrained report with the OpenAI Responses API."""

    name = "openai"
    manages_timeout = True

    def __init__(
        self,
        *,
        api_key: str,
        model_name: str,
        timeout_seconds: int = 60,
        max_output_tokens: int = 5000,
        retry_count: int = 2,
        client: Any | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not api_key and client is None:
            raise ProviderUnavailable(
                "OpenAI is not configured for medical insights.",
                details={"provider": self.name},
            )
        if not model_name or model_name == "extractive-v1":
            raise ProviderUnavailable(
                "Set MEDICAL_AI_MODEL before enabling the OpenAI provider.",
                details={"provider": self.name},
            )
        self.model_name = model_name
        self.timeout_seconds = max(1, int(timeout_seconds))
        self.max_output_tokens = max(256, int(max_output_tokens))
        self.retry_count = max(0, int(retry_count))
        self._sleep = sleep
        self._client = client or self._build_client(api_key)

    def _build_client(self, api_key: str) -> Any:
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise ProviderUnavailable(
                "The openai package is required for the OpenAI medical provider.",
                details={"provider": self.name},
            ) from exc
        return OpenAI(
            api_key=api_key,
            timeout=self.timeout_seconds,
            max_retries=0,
        )

    def generate(self, prompt: str, _context: AnalysisContext) -> Any:
        last_error: Exception | None = None
        deadline = time.monotonic() + self.timeout_seconds
        for attempt in range(self.retry_count + 1):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise MedicalInsightError(
                    "OpenAI medical insight request timed out.",
                    code="provider_timeout",
                ) from last_error
            try:
                response = self._client.responses.create(
                    model=self.model_name,
                    input=prompt,
                    max_output_tokens=self.max_output_tokens,
                    store=False,
                    timeout=remaining,
                    text={
                        "format": {
                            "type": "json_schema",
                            "name": "medical_insight_report",
                            "strict": True,
                            "schema": _strict_json_schema(
                                MedicalInsightReport.model_json_schema()
                            ),
                        }
                    },
                )
                output_text = getattr(response, "output_text", None)
                if not output_text:
                    raise MedicalInsightError(
                        "OpenAI returned no medical insight report.",
                        code="provider_empty_response",
                    )
                # Keep parsing in the analyzer so malformed output gets the
                # same single repair attempt as every other provider.
                return output_text
            except MedicalInsightError:
                raise
            except Exception as exc:
                last_error = exc
                code = _provider_error_code(exc)
                retryable = code in {"provider_timeout", "provider_rate_limited", "provider_unavailable"}
                if not retryable or attempt >= self.retry_count:
                    raise MedicalInsightError(
                        "OpenAI medical insight request failed.",
                        code=code,
                    ) from exc
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise MedicalInsightError(
                        "OpenAI medical insight request timed out.",
                        code="provider_timeout",
                    ) from exc
                self._sleep(min(2**attempt, 4, remaining))
        raise MedicalInsightError(
            "OpenAI medical insight request failed.",
            code="provider_failed",
        ) from last_error


class FakeMedicalAIProvider:
    """Test provider that returns prepared payloads without a network call."""

    name = "fake"

    def __init__(
        self,
        payload: Any | None = None,
        payloads: list[Any] | None = None,
        model_name: str = "fake-v1",
    ) -> None:
        self.model_name = model_name
        self.payload = payload
        self.payloads = list(payloads or [])
        self.calls: list[tuple[str, AnalysisContext]] = []

    def generate(self, prompt: str, context: AnalysisContext) -> Any:
        self.calls.append((prompt, context))
        if self.payloads:
            return copy.deepcopy(self.payloads.pop(0))
        if self.payload is not None:
            return copy.deepcopy(self.payload)
        return ExtractiveMedicalAIProvider().generate(prompt, context)


def get_provider(
    name: str,
    model_name: str = "",
    *,
    api_key: str | None = None,
    timeout_seconds: int | None = None,
    max_output_tokens: int | None = None,
    retry_count: int | None = None,
) -> MedicalAIProvider:
    provider_name = (name or "extractive").strip().lower()
    if provider_name == "extractive":
        return ExtractiveMedicalAIProvider(model_name or "extractive-v1")
    if provider_name == "fake":
        return FakeMedicalAIProvider(model_name=model_name or "fake-v1")
    if provider_name == "openai":
        from app.core.config import settings

        return OpenAIMedicalAIProvider(
            api_key=(
                api_key
                if api_key is not None
                else settings.MEDICAL_AI_OPENAI_API_KEY or settings.OPENAI_API_KEY
            ),
            model_name=model_name or settings.OPENAI_MODEL,
            timeout_seconds=timeout_seconds or settings.MEDICAL_AI_TIMEOUT_SECONDS,
            max_output_tokens=max_output_tokens or settings.MEDICAL_AI_MAX_OUTPUT_TOKENS,
            retry_count=(
                settings.MEDICAL_AI_PROVIDER_RETRY_COUNT
                if retry_count is None
                else retry_count
            ),
        )
    raise ProviderUnavailable(
        f"Medical AI provider '{provider_name}' is not configured.",
        details={"provider": provider_name},
    )


def _first_of(evidence: list[EvidenceItem], *section_types: str) -> EvidenceItem | None:
    for section_type in section_types:
        item = next((item for item in evidence if item.section_type == section_type), None)
        if item:
            return item
    return None


def _take_distinct(
    evidence: list[EvidenceItem],
    section_types: set[str],
    *,
    limit: int,
) -> list[EvidenceItem]:
    result: list[EvidenceItem] = []
    seen: set[str] = set()
    for item in evidence:
        if item.section_type not in section_types:
            continue
        statement = _summary(item.text)
        if not statement or statement in seen:
            continue
        seen.add(statement)
        result.append(item)
        if len(result) >= limit:
            break
    return result


def _finding(
    finding_id: str,
    statement: str,
    explanation: str,
    item: EvidenceItem,
    *,
    interpretation_type: str,
) -> dict[str, Any]:
    return {
        "id": finding_id,
        "statement": statement,
        "plain_explanation": explanation,
        "evidence_ids": [item.evidence_id],
        "evidence_level": "reported_in_document",
        "interpretation_type": interpretation_type,
    }


def _item_for_finding(finding: dict[str, Any], evidence: list[EvidenceItem]) -> EvidenceItem:
    evidence_id = (finding.get("evidence_ids") or [""])[0]
    return next(item for item in evidence if item.evidence_id == evidence_id)


def _summary(text: str, max_chars: int = 360) -> str:
    normalized = " ".join(str(text or "").split())
    if not normalized:
        return ""
    match = re.search(r"[.!?。！？](?:\s|$)", normalized)
    if match and match.end() <= max_chars:
        return normalized[: match.end()].strip()
    if len(normalized) <= max_chars:
        return normalized
    shortened = normalized[:max_chars].rsplit(" ", 1)[0].rstrip(" ,;:")
    return f"{shortened}..."


def _study_type(document_kind: str) -> str:
    return {
        "research_paper": "Research paper",
        "guideline": "Clinical guideline or consensus document",
    }.get(document_kind, "Medical document")


def _coverage(context: AnalysisContext) -> dict[str, Any]:
    return {
        "complete": context.coverage_complete,
        "selected_chunks": len(context.evidence),
        "total_chunks": context.total_chunks,
        "selected_tokens": sum(item.token_count for item in context.evidence),
        "max_input_tokens": context.max_input_tokens,
        "included_sections": context.included_sections,
        "omitted_sections": context.omitted_sections,
    }


def _provider_error_code(exc: Exception) -> str:
    name = exc.__class__.__name__.lower()
    status_code = getattr(exc, "status_code", None)
    if "timeout" in name or isinstance(exc, TimeoutError):
        return "provider_timeout"
    if status_code == 429 or "ratelimit" in name or "rate_limit" in name:
        return "provider_rate_limited"
    if isinstance(status_code, int) and status_code >= 500:
        return "provider_unavailable"
    return "provider_failed"


def _strict_json_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Make Pydantic's schema satisfy Structured Outputs strict mode."""
    schema = copy.deepcopy(schema)

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            properties = value.get("properties")
            if isinstance(properties, dict):
                value["required"] = list(properties)
                value["additionalProperties"] = False
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(schema)
    return schema
