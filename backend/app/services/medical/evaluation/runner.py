"""Deterministic runner for the local medical evaluation suites."""

from __future__ import annotations

from typing import Any, Iterable

from app.services.medical.evaluation.adapters import EvaluationAdapterError, evaluate_case
from app.services.medical.evaluation.gates import hard_gate_summary, quality_metrics
from app.services.medical.evaluation.loader import select_cases
from app.services.medical.evaluation.models import (
    EvaluationCase,
    EvaluationDataset,
    EvaluationReport,
    EvaluationResult,
)


_OBSERVATION_KEYS = {
    "relevant_article_ids",
    "expected_abstention",
}


def run_evaluation(
    dataset: EvaluationDataset,
    *,
    suite: str = "full",
    language: str | None = None,
    tags: Iterable[str] = (),
) -> EvaluationReport:
    """Run selected cases and aggregate stable gates and observations."""
    cases = select_cases(dataset, suite=suite, language=language, tags=tags)
    results = [_run_case(case, dataset.root) for case in cases]
    gate = hard_gate_summary(results)
    report = EvaluationReport(
        schema_version="medical-eval-report-v1",
        dataset_version=dataset.dataset_version,
        suite=suite,
        case_count=len(results),
        passed_cases=sum(result.passed for result in results),
        failed_cases=sum(not result.passed for result in results),
        hard_gates_passed=gate.passed,
        gates=[gate],
        metrics=quality_metrics(results),
        cases=results,
        warnings=[],
    )
    return report


def _run_case(case: EvaluationCase, dataset_root: Any) -> EvaluationResult:
    try:
        actual = evaluate_case(case, dataset_root)
        gate_failures = [
            f"{field}: expected {_display(case.expected[field])}, got {_display(actual.get(field))}"
            for field in case.gate_fields
            if actual.get(field) != case.expected[field]
        ]
        observed_mismatches = [
            f"{field}: expected {_display(expected)}, got {_display(actual.get(field))}"
            for field, expected in sorted(case.expected.items())
            if field not in set(case.gate_fields)
            and field not in _OBSERVATION_KEYS
            and actual.get(field) != expected
        ]
    except (EvaluationAdapterError, ValueError, TypeError, KeyError) as exc:
        actual = {"adapter_error": type(exc).__name__}
        gate_failures = [f"adapter failed: {str(exc) or type(exc).__name__}"]
        observed_mismatches = []
    return EvaluationResult(
        case_id=case.case_id,
        suite=case.suite,
        language=case.language,
        passed=not gate_failures,
        hard_gate_checks=len(case.gate_fields),
        hard_gate_failures=gate_failures,
        observed_mismatches=observed_mismatches,
        expected=case.expected,
        actual=actual,
        metrics=_case_metrics(case, actual),
    )


def _case_metrics(case: EvaluationCase, actual: dict[str, Any]) -> dict[str, float]:
    values: dict[str, float] = {}
    if case.suite == "literature_matching":
        values["candidate_count"] = float(len(actual.get("candidate_ids", [])))
    if case.suite == "clinician_questions":
        values["question_count"] = float(actual.get("question_count", 0))
    return values


def _display(value: Any) -> str:
    return repr(value)
