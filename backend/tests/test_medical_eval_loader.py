"""Validation tests for the versioned, local medical evaluation package."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from app.services.medical.evaluation.loader import (
    EvaluationDatasetError,
    default_dataset_root,
    load_dataset,
)


def _copy_dataset(tmp_path: Path) -> Path:
    target = tmp_path / "medical-eval"
    shutil.copytree(default_dataset_root(), target)
    return target


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def test_default_dataset_has_required_bilingual_case_balance() -> None:
    dataset = load_dataset(require_minimum=32)

    assert len(dataset.cases) >= 32
    assert sum(case.language == "en" for case in dataset.cases) >= 16
    assert sum(case.language == "zh" for case in dataset.cases) >= 16
    assert {case.suite for case in dataset.cases} == {
        "terminology",
        "insight_safety",
        "literature_matching",
        "clinician_questions",
        "visit_preparation",
        "disease_profiles",
    }


def test_loader_rejects_duplicate_manifest_case_ids(tmp_path: Path) -> None:
    root = _copy_dataset(tmp_path)
    manifest_path = root / "manifest.json"
    manifest = _read_json(manifest_path)
    manifest["cases"].append(dict(manifest["cases"][0]))
    manifest["case_count"] += 1
    _write_json(manifest_path, manifest)

    with pytest.raises(EvaluationDatasetError, match="duplicate case ids"):
        load_dataset(root)


def test_loader_rejects_path_escape(tmp_path: Path) -> None:
    root = _copy_dataset(tmp_path)
    manifest_path = root / "manifest.json"
    manifest = _read_json(manifest_path)
    manifest["cases"][0]["path"] = "../outside.json"
    _write_json(manifest_path, manifest)

    with pytest.raises(EvaluationDatasetError, match="evaluation path escapes"):
        load_dataset(root)


def test_loader_rejects_missing_fixture(tmp_path: Path) -> None:
    root = _copy_dataset(tmp_path)
    case_path = root / "literature_matching" / "en_specific_ranking.json"
    case = _read_json(case_path)
    case["fixtures"] = ["fixtures/pubmed/missing.json"]
    _write_json(case_path, case)

    with pytest.raises(EvaluationDatasetError, match="missing fixture"):
        load_dataset(root)


def test_loader_rejects_personal_identifiers_in_case_text(tmp_path: Path) -> None:
    root = _copy_dataset(tmp_path)
    case_path = root / "terminology" / "en_fabry.json"
    case = _read_json(case_path)
    case["input"]["query"] = "Patient ID: ABC123 asks about Fabry disease"
    _write_json(case_path, case)

    with pytest.raises(EvaluationDatasetError, match="disallowed personal identifier"):
        load_dataset(root)


def test_loader_rejects_personal_identifiers_in_fixture_text(tmp_path: Path) -> None:
    root = _copy_dataset(tmp_path)
    fixture_path = root / "fixtures" / "pubmed" / "fabry.json"
    fixture = _read_json(fixture_path)
    fixture[0]["abstract"] = "Patient ID: ABC123 was included in the synthetic record."
    _write_json(fixture_path, fixture)

    with pytest.raises(EvaluationDatasetError, match="fixture contains a disallowed personal identifier"):
        load_dataset(root)


def test_loader_rejects_structured_phone_in_fixture(tmp_path: Path) -> None:
    root = _copy_dataset(tmp_path)
    fixture_path = root / "fixtures" / "pubmed" / "fabry.json"
    fixture = _read_json(fixture_path)
    fixture[0]["phone"] = "13800138000"
    _write_json(fixture_path, fixture)

    with pytest.raises(EvaluationDatasetError, match="fixture contains a disallowed personal identifier"):
        load_dataset(root)


def test_loader_rejects_structured_patient_id_in_fixture(tmp_path: Path) -> None:
    root = _copy_dataset(tmp_path)
    fixture_path = root / "fixtures" / "pubmed" / "fabry.json"
    fixture = _read_json(fixture_path)
    fixture[0]["patient_id"] = "ABC123"
    _write_json(fixture_path, fixture)

    with pytest.raises(EvaluationDatasetError, match="fixture contains a disallowed personal identifier"):
        load_dataset(root)


def test_loader_allows_iso_publication_date(tmp_path: Path) -> None:
    root = _copy_dataset(tmp_path)
    case_path = root / "terminology" / "en_fabry.json"
    case = _read_json(case_path)
    case["input"]["publication_date"] = "2025-03-01"
    _write_json(case_path, case)

    load_dataset(root)


def test_loader_allows_public_medical_identifier(tmp_path: Path) -> None:
    root = _copy_dataset(tmp_path)
    fixture_path = root / "fixtures" / "pubmed" / "fabry.json"
    fixture = _read_json(fixture_path)
    fixture[0]["pmid"] = "123456789"
    _write_json(fixture_path, fixture)

    load_dataset(root)


def test_loader_rejects_explicit_phone_number(tmp_path: Path) -> None:
    root = _copy_dataset(tmp_path)
    case_path = root / "terminology" / "en_fabry.json"
    case = _read_json(case_path)
    case["input"]["contact"] = "Phone: +1 555-010-1234"
    _write_json(case_path, case)

    with pytest.raises(EvaluationDatasetError, match="disallowed personal identifier"):
        load_dataset(root)


def test_loader_rejects_structured_phone_without_label(tmp_path: Path) -> None:
    root = _copy_dataset(tmp_path)
    case_path = root / "terminology" / "en_fabry.json"
    case = _read_json(case_path)
    case["input"]["phone"] = "13800138000"
    _write_json(case_path, case)

    with pytest.raises(EvaluationDatasetError, match="disallowed personal identifier"):
        load_dataset(root)


def test_loader_rejects_structured_patient_id(tmp_path: Path) -> None:
    root = _copy_dataset(tmp_path)
    case_path = root / "terminology" / "en_fabry.json"
    case = _read_json(case_path)
    case["input"]["patient_id"] = "ABC123"
    _write_json(case_path, case)

    with pytest.raises(EvaluationDatasetError, match="disallowed personal identifier"):
        load_dataset(root)


def test_loader_rejects_unsupported_case_schema(tmp_path: Path) -> None:
    root = _copy_dataset(tmp_path)
    case_path = root / "terminology" / "en_fabry.json"
    case = _read_json(case_path)
    case["schema_version"] = "medical-eval-v99"
    _write_json(case_path, case)

    with pytest.raises(EvaluationDatasetError, match="case en_terminology_fabry_001 file is invalid"):
        load_dataset(root)
