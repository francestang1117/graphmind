"""Hard regression gates and aggregate quality observations."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from app.services.medical.evaluation.metrics import (
    accuracy,
    mean_reciprocal_rank,
    precision_at_k,
    rate,
    recall_at_k,
)
from app.services.medical.evaluation.models import EvaluationResult, GateSummary


def hard_gate_summary(results: Iterable[EvaluationResult]) -> GateSummary:
    """Summarize all case-declared hard fields and retain failing case paths."""
    rows = list(results)
    failures: list[str] = []
    checks = 0
    for result in rows:
        checks += result.hard_gate_checks
        failures.extend(f"{result.case_id}: {failure}" for failure in result.hard_gate_failures)
    if not rows or checks == 0:
        failures.append("no hard regression checks were executed")
    return GateSummary(
        name="hard_regression_gates",
        passed=not failures,
        checks=checks,
        failures=failures,
    )


def quality_metrics(results: Iterable[EvaluationResult]) -> dict[str, float]:
    """Compute observations without imposing unreviewed quality thresholds."""
    rows = list(results)
    metrics: dict[str, float] = {}

    terminology = [row for row in rows if row.suite == "terminology"]
    if terminology:
        metrics["terminology_expected_behavior_rate"] = accuracy(
            not row.observed_mismatches for row in terminology
        )

    insight = [row for row in rows if row.suite == "insight_safety"]
    if insight:
        metrics["insight_expected_behavior_rate"] = accuracy(
            not row.observed_mismatches for row in insight
        )

    literature = [row for row in rows if row.suite == "literature_matching"]
    if literature:
        precisions: list[float] = []
        recalls: list[float] = []
        retrieved_rows: list[list[str]] = []
        relevant_rows: list[list[str]] = []
        abstention_checks: list[bool] = []
        reason_checks: list[bool] = []
        for row in literature:
            retrieved = [str(value) for value in row.actual.get("candidate_ids", [])]
            relevant = [str(value) for value in row.expected.get("relevant_article_ids", [])]
            if "expected_abstention" in row.expected:
                abstention_checks.append(
                    bool(row.actual.get("abstained")) == bool(row.expected["expected_abstention"])
                )
                if row.expected["expected_abstention"]:
                    continue
            retrieved_rows.append(retrieved)
            relevant_rows.append(relevant)
            precisions.append(precision_at_k(retrieved, relevant, 3))
            recalls.append(recall_at_k(retrieved, relevant, 5))
            if row.actual.get("reason_complete") is not None:
                reason_checks.append(bool(row.actual["reason_complete"]))
        if precisions:
            metrics["precision_at_3"] = round(sum(precisions) / len(precisions), 4)
            metrics["recall_at_5"] = round(sum(recalls) / len(recalls), 4)
            metrics["mrr"] = mean_reciprocal_rank(retrieved_rows, relevant_rows)
        if abstention_checks:
            metrics["correct_abstention_rate"] = accuracy(abstention_checks)
        if reason_checks:
            metrics["match_reason_completeness"] = accuracy(reason_checks)

    questions = [row for row in rows if row.suite == "clinician_questions"]
    if questions:
        bound = [
            bool(row.actual.get("all_bound"))
            for row in questions
            if row.expected.get("all_bound") is True
        ]
        if bound:
            metrics["question_evidence_binding_rate"] = accuracy(bound)
        expected_question_rows = [
            row for row in questions if int(row.expected.get("question_count", 0)) > 0
        ]
        if expected_question_rows:
            metrics["question_topic_coverage"] = rate(
                sum(bool(row.actual.get("question_count")) for row in expected_question_rows),
                len(expected_question_rows),
            )

    return {key: value for key, value in sorted(metrics.items())}
