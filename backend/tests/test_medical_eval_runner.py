"""End-to-end tests for the offline medical evaluation runner."""

from app.services.medical.evaluation.loader import load_dataset, select_cases
from app.services.medical.evaluation.models import EvaluationDataset
from app.services.medical.evaluation.report import render_json, render_markdown
from app.services.medical.evaluation.runner import run_evaluation


def test_full_evaluation_passes_all_declared_hard_gates() -> None:
    dataset = load_dataset(require_minimum=32)
    report = run_evaluation(dataset, suite="full")

    assert report.case_count >= 32
    assert report.passed_cases == report.case_count
    assert report.failed_cases == 0
    assert report.hard_gates_passed is True
    assert report.gates[0].checks > 0
    assert report.metrics["recall_at_5"] == 1.0


def test_smoke_suite_is_a_stable_subset() -> None:
    dataset = load_dataset(require_minimum=32)
    selected = select_cases(dataset, suite="smoke")
    report = run_evaluation(dataset, suite="smoke")

    assert selected
    assert report.case_count == len(selected)
    assert report.hard_gates_passed is True


def test_evaluation_report_is_byte_stable() -> None:
    dataset = load_dataset(require_minimum=32)
    first = run_evaluation(dataset, suite="full")
    second = run_evaluation(dataset, suite="full")

    assert render_json(first) == render_json(second)
    assert "Hard gates: PASS" in render_markdown(first)


def test_one_failed_case_does_not_stop_the_remaining_cases() -> None:
    dataset = load_dataset(require_minimum=32)
    first = dataset.cases[0].model_copy(
        update={
            "expected": {
                **dataset.cases[0].expected,
                "resolution_status": "intentionally_wrong",
            }
        }
    )
    limited = EvaluationDataset(
        root=dataset.root,
        manifest=dataset.manifest,
        cases=(first, dataset.cases[1]),
    )

    report = run_evaluation(limited, suite="all")

    assert report.case_count == 2
    assert report.failed_cases == 1
    assert report.passed_cases == 1
    assert report.hard_gates_passed is False
    assert any(case.case_id == dataset.cases[0].case_id for case in report.cases)
    markdown = render_markdown(report)
    assert "Expected:" in markdown
    assert "Actual:" in markdown
