"""End-to-end tests for the offline medical evaluation runner."""

import pytest

from app.services.medical.evaluation.adapters import (
    evaluate_insight_safety,
    evaluate_terminology,
)
from app.services.medical.evaluation.gates import quality_metrics
from app.services.medical.evaluation.loader import (
    EvaluationDatasetError,
    load_dataset,
    select_cases,
)
from app.services.medical.evaluation.models import EvaluationDataset, EvaluationResult
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


def test_empty_selection_fails_closed() -> None:
    dataset = load_dataset(require_minimum=32)

    with pytest.raises(EvaluationDatasetError, match="no evaluation cases selected"):
        run_evaluation(dataset, suite="full", language="ja")


def test_selection_without_hard_gates_fails_closed() -> None:
    dataset = load_dataset(require_minimum=32)
    ungated = dataset.cases[0].model_copy(update={"gate_fields": []})
    limited = EvaluationDataset(
        root=dataset.root,
        manifest=dataset.manifest,
        cases=(ungated,),
    )

    with pytest.raises(EvaluationDatasetError, match="declare no hard gates"):
        run_evaluation(limited, suite="all")


def test_terminology_evaluation_records_the_release_boundary() -> None:
    dataset = load_dataset(require_minimum=32)
    ready = next(case for case in dataset.cases if case.case_id == "en_terminology_fabry_001")
    blocked = next(
        case
        for case in dataset.cases
        if case.case_id == "en_terminology_als_ambiguous_001"
    )

    released = evaluate_terminology(ready, dataset.root)
    withheld = evaluate_terminology(blocked, dataset.root)

    assert released["repository_create_count"] == 1
    assert released["queue_count"] == 1
    assert released["provider_search_count"] == 1
    assert len(released["released_queries"]) == 1
    assert withheld["repository_create_count"] == 0
    assert withheld["queue_count"] == 0
    assert withheld["provider_search_count"] == 0
    assert withheld["released_queries"] == []


def test_terminology_privacy_case_only_releases_normalized_terms() -> None:
    dataset = load_dataset(require_minimum=32)
    case = next(
        case
        for case in dataset.cases
        if case.case_id == "zh_terminology_privacy_001"
    )

    actual = evaluate_terminology(case, dataset.root)
    released_query = " ".join(actual["released_queries"])

    assert "戈谢病" not in released_query
    assert "患者" not in released_query
    assert "张三" not in released_query


def test_terminology_confirmation_failures_never_reach_release_boundary() -> None:
    dataset = load_dataset(require_minimum=32)

    for case_id, error_code in (
        (
            "en_terminology_fabry_unconfirmed_001",
            "external_search_confirmation_required",
        ),
        (
            "zh_terminology_fabry_stale_confirmation_001",
            "external_search_query_changed",
        ),
    ):
        case = next(case for case in dataset.cases if case.case_id == case_id)
        actual = evaluate_terminology(case, dataset.root)

        assert actual["error_code"] == error_code
        assert actual["external_query_allowed"] is False
        assert actual["repository_create_count"] == 0
        assert actual["queue_count"] == 0
        assert actual["provider_search_count"] == 0


def test_insight_evaluation_runs_analyzer_and_repair_path() -> None:
    dataset = load_dataset(require_minimum=32)
    case = next(
        case
        for case in dataset.cases
        if case.case_id == "en_insight_treatment_safety_001"
    )

    actual = evaluate_insight_safety(case, dataset.root)

    assert actual["safety_valid"] is False
    assert actual["provider_call_count"] == 2


def test_insight_evaluation_gates_pipeline_acceptance_and_rejection() -> None:
    dataset = load_dataset(require_minimum=32)
    cases = {
        "en_insight_safe_association_001": ("accepted", 1),
        "en_insight_speculation_001": ("rejected", 2),
    }

    for case_id, expected in cases.items():
        case = next(case for case in dataset.cases if case.case_id == case_id)
        actual = evaluate_insight_safety(case, dataset.root)
        assert (actual["pipeline_status"], actual["provider_call_count"]) == expected


def test_abstention_does_not_count_as_complete_match_reasons() -> None:
    result = EvaluationResult(
        case_id="en_literature_abstention_001",
        suite="literature_matching",
        language="en",
        passed=True,
        hard_gate_checks=1,
        expected={"expected_abstention": True},
        actual={"abstained": True, "candidate_ids": [], "reason_complete": None},
    )

    metrics = quality_metrics([result])

    assert metrics["correct_abstention_rate"] == 1.0
    assert "match_reason_completeness" not in metrics


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
