"""Orchestrate one evidence-backed medical document analysis."""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass
from typing import Any, Iterable

from pydantic import ValidationError

from app.services.medical.ai.citation_validator import CitationValidation, validate_citations
from app.services.medical.ai.context_builder import AnalysisContext, ContextBuilder
from app.services.medical.ai.exceptions import (
    MedicalInsightError,
    MedicalInsightValidationError,
)
from app.services.medical.ai.models import MedicalInsightReport
from app.services.medical.ai.prompt_builder import build_prompt, build_repair_prompt
from app.services.medical.ai.provider import MedicalAIProvider, get_provider
from app.services.medical.ai.safety_validator import SafetyValidation, validate_safety

log = logging.getLogger(__name__)


@dataclass
class AnalysisOutput:
    report: MedicalInsightReport
    context: AnalysisContext
    citations: CitationValidation
    safety: SafetyValidation


class MedicalInsightAnalyzer:
    """Turn persisted chunks into a validated report without storing raw prompts."""

    def __init__(
        self,
        provider: MedicalAIProvider | None = None,
        *,
        max_input_tokens: int = 12000,
        timeout_seconds: int = 30,
        redact_pii: bool = True,
        schema_version: str = "medical-insights-v1",
        prompt_version: str = "medical-insights-v1",
        context_builder: ContextBuilder | None = None,
    ) -> None:
        if provider is None:
            from app.core.config import settings

            provider = get_provider(settings.MEDICAL_AI_PROVIDER, settings.MEDICAL_AI_MODEL)
            max_input_tokens = settings.MEDICAL_AI_MAX_INPUT_TOKENS
            timeout_seconds = settings.MEDICAL_AI_TIMEOUT_SECONDS
            redact_pii = settings.MEDICAL_AI_REDACT_PII
            schema_version = settings.MEDICAL_AI_SCHEMA_VERSION
            prompt_version = settings.MEDICAL_AI_PROMPT_VERSION

        self.provider = provider
        self.max_input_tokens = max(1, int(max_input_tokens))
        self.timeout_seconds = max(1, int(timeout_seconds))
        self.redact_pii = redact_pii
        self.schema_version = schema_version
        self.prompt_version = prompt_version
        self.context_builder = context_builder or ContextBuilder()

    def run(
        self,
        chunks: Iterable[dict[str, Any]],
        *,
        sections: Iterable[dict[str, Any]] | None = None,
        title: str = "",
        document_kind: str = "unknown",
        language: str = "unknown",
    ) -> AnalysisOutput:
        context = self.context_builder.build(
            chunks,
            sections=sections,
            title=title,
            document_kind=document_kind,
            language=language,
            max_input_tokens=self.max_input_tokens,
            redact_pii=self.redact_pii,
        )
        if not context.evidence:
            raise MedicalInsightValidationError(
                "The document has no extractable evidence for analysis.",
                errors=["no evidence chunks"],
            )

        prompt = build_prompt(context, schema_version=self.schema_version)
        candidate = self._generate(prompt, context)
        report, errors = self._parse_report(candidate)
        if report is not None:
            report = self._normalize_report(report, context)
            validation = self._validate(report, context)
            if validation is None:
                return self._output(report, context)
            errors.extend(validation)

        repair_prompt = build_repair_prompt(
            context,
            candidate,
            errors,
            schema_version=self.schema_version,
        )
        repaired = self._generate(repair_prompt, context)
        repaired_report, repair_errors = self._parse_report(repaired)
        if repaired_report is not None:
            repaired_report = self._normalize_report(repaired_report, context)
            validation = self._validate(repaired_report, context)
            if validation is None:
                return self._output(repaired_report, context)
            repair_errors.extend(validation)

        raise MedicalInsightValidationError(
            "Medical insight output failed citation or safety validation.",
            errors=_unique([*errors, *repair_errors]) or ["invalid provider output"],
        )

    def _generate(self, prompt: str, context: AnalysisContext) -> Any:
        executor = ThreadPoolExecutor(max_workers=1)
        future = executor.submit(self.provider.generate, prompt, context)
        try:
            return future.result(timeout=self.timeout_seconds)
        except FutureTimeout as exc:
            future.cancel()
            raise MedicalInsightError(
                "Medical insight provider timed out.",
                code="provider_timeout",
            ) from exc
        except MedicalInsightError:
            raise
        except Exception as exc:
            log.warning("Medical insight provider failed: %s", exc)
            raise MedicalInsightError(
                "Medical insight provider failed.",
                code="provider_failed",
            ) from exc
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    def _parse_report(self, candidate: Any) -> tuple[MedicalInsightReport | None, list[str]]:
        if isinstance(candidate, MedicalInsightReport):
            return candidate, []
        payload = candidate
        if isinstance(candidate, str):
            payload_text = candidate.strip()
            if payload_text.startswith("```"):
                payload_text = payload_text.strip("`").strip()
                if payload_text.startswith("json"):
                    payload_text = payload_text[4:].lstrip()
            try:
                payload = json.loads(payload_text)
            except json.JSONDecodeError:
                return None, ["provider output is not valid JSON"]
        if not isinstance(payload, dict):
            return None, ["provider output must be a JSON object"]
        try:
            return MedicalInsightReport.model_validate(payload), []
        except ValidationError as exc:
            # Keep field paths, not the raw model output, in the task record.
            errors = [".".join(str(part) for part in error["loc"]) + ": " + error["msg"] for error in exc.errors()]
            return None, errors

    def _validate(self, report: MedicalInsightReport, context: AnalysisContext) -> list[str] | None:
        citation = validate_citations(report, context)
        safety = validate_safety(report)
        errors = [*citation.errors, *safety.errors]
        return errors or None

    def _normalize_report(
        self,
        report: MedicalInsightReport,
        context: AnalysisContext,
    ) -> MedicalInsightReport:
        warnings = _unique([*context.warnings, *report.warnings, "not_medical_advice"])
        return report.model_copy(
            update={
                "schema_version": self.schema_version,
                "document_kind": context.document_kind,
                "language": context.language,
                "warnings": warnings,
            }
        )

    def _output(self, report: MedicalInsightReport, context: AnalysisContext) -> AnalysisOutput:
        return AnalysisOutput(
            report=report,
            context=context,
            citations=validate_citations(report, context),
            safety=validate_safety(report),
        )


def _unique(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(str(value) for value in values if value))
