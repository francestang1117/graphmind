"""Unit tests for deterministic medical evaluation metrics."""

from app.services.medical.evaluation.metrics import (
    accuracy,
    mean_reciprocal_rank,
    precision_at_k,
    rate,
    recall_at_k,
    stable_unique,
)


def test_precision_and_recall_have_stable_empty_conventions() -> None:
    assert precision_at_k([], [], 3) == 1.0
    assert precision_at_k([], ["a"], 3) == 0.0
    assert recall_at_k([], [], 5) == 1.0
    assert recall_at_k(["a"], [], 5) == 0.0


def test_precision_recall_and_mrr_use_ranked_rows() -> None:
    retrieved = ["wrong", "right", "other"]
    relevant = ["right"]

    assert precision_at_k(retrieved, relevant, 3) == round(1 / 3, 4)
    assert recall_at_k(retrieved, relevant, 2) == 1.0
    assert mean_reciprocal_rank([retrieved], [relevant]) == 0.5


def test_aggregate_helpers_are_deterministic_and_safe() -> None:
    assert accuracy([True, False, True]) == round(2 / 3, 4)
    assert accuracy([]) == 0.0
    assert rate(2, 4) == 0.5
    assert rate(2, 0) == 0.0
    assert stable_unique(["a", "b", "a", "", "b"]) == ["a", "b"]
