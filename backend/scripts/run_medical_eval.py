#!/usr/bin/env python3
"""Run the repository-local deterministic medical evaluation suites."""

from __future__ import annotations

import argparse
import sys

from app.services.medical.evaluation.loader import EvaluationDatasetError, load_dataset
from app.services.medical.evaluation.report import render_markdown, write_report
from app.services.medical.evaluation.runner import run_evaluation


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--suite",
        choices=("smoke", "full", "terminology", "insight_safety", "literature_matching", "clinician_questions", "visit_preparation", "disease_profiles"),
        default="full",
    )
    parser.add_argument("--language", choices=("en", "zh"))
    parser.add_argument("--json-output")
    parser.add_argument("--markdown-output")
    parser.add_argument(
        "--fail-on-gate",
        action="store_true",
        help="return exit code 1 when a hard regression gate fails",
    )
    args = parser.parse_args(argv)

    try:
        dataset = load_dataset(require_minimum=32)
        report = run_evaluation(
            dataset,
            suite=args.suite,
            language=args.language,
        )
        write_report(
            report,
            json_output=args.json_output,
            markdown_output=args.markdown_output,
        )
    except (EvaluationDatasetError, ValueError, OSError) as exc:
        print(f"medical evaluation data error: {exc}", file=sys.stderr)
        return 2

    if not args.markdown_output:
        print(render_markdown(report), end="")
    else:
        print(
            f"Medical evaluation {report.dataset_version}: "
            f"{report.passed_cases}/{report.case_count} hard-gate cases passed; "
            f"hard gates={'PASS' if report.hard_gates_passed else 'FAIL'}"
        )
    return 1 if args.fail_on_gate and not report.hard_gates_passed else 0


if __name__ == "__main__":
    raise SystemExit(main())
