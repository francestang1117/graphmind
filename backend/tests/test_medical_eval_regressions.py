"""High-value regression checks represented by the medical baseline."""

from app.services.medical.evidence_matching.study_card_builder import (
    classify_study_category,
)
from app.services.medical.evaluation.loader import load_dataset
from app.services.medical.evaluation.runner import run_evaluation


def test_preclinical_publication_type_is_not_a_clinical_study() -> None:
    assert classify_study_category(["Preclinical Study"]) == "preclinical"
    assert classify_study_category(["Animal Experimentation"]) == "preclinical"


def test_hard_gate_baseline_covers_privacy_safety_and_abstention_cases() -> None:
    dataset = load_dataset(require_minimum=32)
    report = run_evaluation(dataset, suite="full")
    case_ids = {case.case_id for case in dataset.cases}

    assert "zh_terminology_privacy_001" in case_ids
    assert "en_insight_treatment_safety_001" in case_ids
    assert "zh_literature_no_candidates_001" in case_ids
    assert report.hard_gates_passed is True
