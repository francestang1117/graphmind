"""Load and validate the immutable, local medical evaluation dataset."""

from __future__ import annotations

import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

from pydantic import ValidationError

from app.services.medical.evaluation.models import (
    EvaluationCase,
    EvaluationDataset,
    EvaluationManifest,
)


class EvaluationDatasetError(ValueError):
    """Raised when an evaluation package cannot be trusted or executed."""


_EMAIL = re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b")
_PHONE = re.compile(
    r"(?i)(?:phone|telephone|mobile|tel|电话|手机|联系电话)\s*"
    r"(?:number|no\.?|号码)?\s*[:：]?\s*\+?\d[\d .()\-]{7,}\d"
    r"|(?<!\w)\+?\d{1,3}(?:[ .\-]\(?\d{3,4}\)?){2,3}(?!\w)"
)
_GOVERNMENT_ID = re.compile(r"(?<!\w)\d{17}[\dXx](?!\w)")
_RECORD_ID = re.compile(
    r"(?i)(?:patient|medical\s+record|住院|病历|患者)\s*"
    r"(?:id|number|no\.?|编号|号)?\s*[:#-]\s*[A-Za-z0-9_-]{3,}"
)
_PUBLIC_DATE_FIELDS = {
    "date_from",
    "date_to",
    "fetched_at",
    "last_reviewed",
    "publication_date",
}


def default_dataset_root() -> Path:
    """Return the repository-local v1 dataset directory."""
    return Path(__file__).resolve().parents[4] / "evals" / "medical" / "v1"


def load_dataset(
    root: str | Path | None = None,
    *,
    require_minimum: int = 0,
    include_deprecated: bool = False,
) -> EvaluationDataset:
    """Load a dataset and validate every manifest and case reference.

    The loader is intentionally filesystem-only. It never downloads source
    material and never interprets a case's free-form text as an instruction.
    """
    root_path = Path(root or default_dataset_root()).expanduser().resolve()
    if not root_path.is_dir():
        raise EvaluationDatasetError("evaluation dataset directory is missing")
    manifest_path = root_path / "manifest.json"
    manifest = _read_model(manifest_path, EvaluationManifest, "manifest")
    if manifest.schema_version != "medical-eval-v1":
        raise EvaluationDatasetError("unsupported evaluation schema version")
    if manifest.case_count != len(manifest.cases):
        raise EvaluationDatasetError("manifest case_count does not match references")
    if len({item.case_id for item in manifest.cases}) != len(manifest.cases):
        raise EvaluationDatasetError("manifest contains duplicate case ids")

    cases: list[EvaluationCase] = []
    seen_ids: set[str] = set()
    for reference in manifest.cases:
        case_path = _safe_child(root_path, reference.path)
        case = _read_model(case_path, EvaluationCase, f"case {reference.case_id}")
        if case.case_id != reference.case_id or case.suite != reference.suite:
            raise EvaluationDatasetError(
                f"manifest reference does not match case file {reference.case_id}"
            )
        if case.case_id in seen_ids:
            raise EvaluationDatasetError(f"duplicate case id {case.case_id}")
        seen_ids.add(case.case_id)
        if case.review_status == "deprecated" and not include_deprecated:
            continue
        for fixture in case.fixtures:
            fixture_path = _safe_child(root_path, fixture)
            if not fixture_path.is_file():
                raise EvaluationDatasetError(
                    f"case {case.case_id} references a missing fixture"
                )
            try:
                fixture_text = fixture_path.read_text(encoding="utf-8")
            except (OSError, UnicodeError) as exc:
                raise EvaluationDatasetError(
                    f"case {case.case_id} references an unreadable fixture"
                ) from exc
            fixture_pii_path = _find_sensitive_text(
                fixture_text,
                f"fixture:{fixture}",
            )
            if fixture_pii_path:
                raise EvaluationDatasetError(
                    f"case {case.case_id} fixture contains a disallowed personal identifier"
                )
        pii_path = _find_sensitive_text(case.model_dump(mode="json"))
        if pii_path:
            raise EvaluationDatasetError(
                f"case {case.case_id} contains a disallowed personal identifier at {pii_path}"
            )
        for field in case.gate_fields:
            if field not in case.expected:
                raise EvaluationDatasetError(
                    f"case {case.case_id} gates an absent expected field {field}"
                )
        cases.append(case)

    if len(cases) < int(require_minimum):
        raise EvaluationDatasetError(
            f"evaluation dataset contains {len(cases)} cases; {require_minimum} required"
        )
    return EvaluationDataset(root=root_path, manifest=manifest, cases=tuple(cases))


def select_cases(
    dataset: EvaluationDataset,
    *,
    suite: str | None = None,
    language: str | None = None,
    tags: Iterable[str] = (),
) -> tuple[EvaluationCase, ...]:
    """Select cases without changing their deterministic case ordering."""
    tag_set = {str(tag).strip() for tag in tags if str(tag).strip()}
    if suite and suite not in {"smoke", "full", "all"} and not any(
        case.suite == suite for case in dataset.cases
    ):
        raise EvaluationDatasetError(f"unknown evaluation suite {suite}")
    selected = []
    for case in dataset.cases:
        if suite == "smoke" and "smoke" not in case.tags:
            continue
        if suite not in {None, "smoke", "full", "all"} and case.suite != suite:
            continue
        if language and case.language != language:
            continue
        if tag_set and not tag_set.issubset(set(case.tags)):
            continue
        selected.append(case)
    return tuple(sorted(selected, key=lambda item: item.case_id))


def _read_model(path: Path, model: Any, label: str) -> Any:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return model.model_validate(value)
    except FileNotFoundError as exc:
        raise EvaluationDatasetError(f"{label} file is missing") from exc
    except (OSError, UnicodeError, json.JSONDecodeError, ValidationError) as exc:
        raise EvaluationDatasetError(f"{label} file is invalid") from exc


def _safe_child(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if root != path and root not in path.parents:
        raise EvaluationDatasetError("evaluation path escapes dataset root")
    return path


def _find_sensitive_text(value: Any, path: str = "$") -> str | None:
    if isinstance(value, str):
        if _is_public_date_field(path, value):
            return None
        for pattern in (_EMAIL, _PHONE, _GOVERNMENT_ID, _RECORD_ID):
            if pattern.search(value):
                return path
        return None
    if isinstance(value, dict):
        for key in sorted(value):
            result = _find_sensitive_text(value[key], f"{path}.{key}")
            if result:
                return result
    elif isinstance(value, list):
        for index, item in enumerate(value):
            result = _find_sensitive_text(item, f"{path}[{index}]")
            if result:
                return result
    return None


def _is_public_date_field(path: str, value: str) -> bool:
    """Avoid treating valid public dates as phone numbers or identifiers."""
    field_name = path.rsplit(".", 1)[-1].split("[", 1)[0]
    if field_name not in _PUBLIC_DATE_FIELDS:
        return False
    try:
        if "T" in value or "t" in value:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        else:
            date.fromisoformat(value)
    except ValueError:
        return False
    return True
