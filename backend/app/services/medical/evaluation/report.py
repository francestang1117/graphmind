"""Serialize evaluation output for local development and GitHub Actions."""

from __future__ import annotations

import json
from pathlib import Path

from app.services.medical.evaluation.models import EvaluationReport


def render_json(report: EvaluationReport) -> str:
    """Render stable, sorted JSON suitable for artifact comparison."""
    return json.dumps(
        report.model_dump(mode="json"),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"


def render_markdown(report: EvaluationReport) -> str:
    """Render a compact developer-facing summary without raw medical prose."""
    lines = [
        f"# Medical evaluation {report.dataset_version}",
        "",
        f"- Suite: `{report.suite}`",
        f"- Cases: {report.case_count}",
        f"- Cases passing hard fields: {report.passed_cases}",
        f"- Cases with hard failures: {report.failed_cases}",
        f"- Hard gates: {'PASS' if report.hard_gates_passed else 'FAIL'}",
        "",
        "## Gates",
        "",
        "| Gate | Checks | Status |",
        "| --- | ---: | --- |",
    ]
    for gate in report.gates:
        lines.append(
            f"| `{gate.name}` | {gate.checks} | {'PASS' if gate.passed else 'FAIL'} |"
        )
    lines.extend(["", "## Observations", "", "| Metric | Value |", "| --- | ---: |"])
    for name, value in report.metrics.items():
        lines.append(f"| `{name}` | {value:.4f} |")
    failures = [
        case
        for case in report.cases
        if case.hard_gate_failures
    ]
    if failures:
        lines.extend(["", "## Hard Gate Failures", ""])
        for case in failures:
            lines.extend(
                [
                    f"- `{case.case_id}`: {'; '.join(case.hard_gate_failures)}",
                    f"  - Expected: `{_compact_json(case.expected)}`",
                    f"  - Actual: `{_compact_json(case.actual)}`",
                ]
            )
    observed = [
        (case.case_id, mismatch)
        for case in report.cases
        for mismatch in case.observed_mismatches
    ]
    if observed:
        lines.extend(["", "## Observed Regressions", ""])
        lines.extend(f"- `{case_id}`: {mismatch}" for case_id, mismatch in observed)
    if report.warnings:
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- {warning}" for warning in report.warnings)
    return "\n".join(lines) + "\n"


def _compact_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def write_report(report: EvaluationReport, *, json_output: str | Path | None = None, markdown_output: str | Path | None = None) -> None:
    """Write selected report formats, creating only their requested parents."""
    for target, content in (
        (json_output, render_json(report)),
        (markdown_output, render_markdown(report)),
    ):
        if target is None:
            continue
        path = Path(target)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
