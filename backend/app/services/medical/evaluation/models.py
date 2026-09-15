"""Strict schemas for the versioned medical evaluation dataset and reports."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


EvalSuite = Literal[
    "terminology",
    "insight_safety",
    "literature_matching",
    "clinician_questions",
]
ReviewStatus = Literal["engineering_reviewed", "clinical_reviewed", "deprecated"]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ManifestCase(_StrictModel):
    """One case file reference in the dataset manifest."""

    case_id: str = Field(min_length=1, max_length=120)
    suite: EvalSuite
    path: str = Field(min_length=1, max_length=255)


class EvaluationManifest(_StrictModel):
    """The index for one immutable evaluation dataset version."""

    schema_version: Literal["medical-eval-v1"]
    dataset_version: str = Field(min_length=1, max_length=64)
    description: str = Field(min_length=1, max_length=1000)
    case_count: int = Field(ge=1, le=10000)
    cases: list[ManifestCase] = Field(min_length=1, max_length=10000)


class EvaluationCase(_StrictModel):
    """One deterministic, reviewable evaluation input and expectation."""

    schema_version: Literal["medical-eval-v1"]
    case_id: str = Field(
        min_length=3,
        max_length=120,
        pattern=r"^[a-z0-9][a-z0-9_-]+$",
    )
    suite: EvalSuite
    language: Literal["en", "zh", "ja"]
    tags: list[str] = Field(min_length=1, max_length=20)
    review_status: ReviewStatus
    input: dict[str, Any]
    expected: dict[str, Any] = Field(min_length=1)
    rationale: str = Field(min_length=1, max_length=2000)
    source_references: list[str] = Field(default_factory=list, max_length=20)
    fixtures: list[str] = Field(default_factory=list, max_length=20)
    gate_fields: list[str] = Field(default_factory=list, max_length=20)
    last_reviewed: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")

    @field_validator("case_id", "rationale", "last_reviewed")
    @classmethod
    def trim_required_strings(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("evaluation fields must not be blank")
        return value

    @field_validator("tags", "source_references", "fixtures", "gate_fields")
    @classmethod
    def trim_list_values(cls, values: list[str]) -> list[str]:
        cleaned = [str(value).strip() for value in values]
        if any(not value for value in cleaned):
            raise ValueError("evaluation list values must not be blank")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("evaluation list values must be unique")
        return cleaned


class EvaluationResult(_StrictModel):
    """The stable output for one case."""

    case_id: str
    suite: EvalSuite
    language: str
    passed: bool
    hard_gate_checks: int = Field(ge=0)
    hard_gate_failures: list[str] = Field(default_factory=list)
    observed_mismatches: list[str] = Field(default_factory=list)
    expected: dict[str, Any]
    actual: dict[str, Any]
    metrics: dict[str, float] = Field(default_factory=dict)


class GateSummary(_StrictModel):
    """A named aggregate gate suitable for CI and an Actions summary."""

    name: str
    passed: bool
    checks: int = Field(ge=0)
    failures: list[str] = Field(default_factory=list)


class EvaluationReport(_StrictModel):
    """Machine-readable evaluation output with no timing or environment noise."""

    schema_version: Literal["medical-eval-report-v1"]
    dataset_version: str
    suite: str
    case_count: int = Field(ge=0)
    passed_cases: int = Field(ge=0)
    failed_cases: int = Field(ge=0)
    hard_gates_passed: bool
    gates: list[GateSummary] = Field(default_factory=list)
    metrics: dict[str, float] = Field(default_factory=dict)
    cases: list[EvaluationResult] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class EvaluationDataset:
    """Loaded cases plus the directory used to resolve local fixtures."""

    root: Any
    manifest: EvaluationManifest
    cases: tuple[EvaluationCase, ...]

    @property
    def dataset_version(self) -> str:
        return self.manifest.dataset_version
