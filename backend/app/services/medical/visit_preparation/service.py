"""Application service for the clinician-question and visit-brief workflow."""

from __future__ import annotations

from typing import Any

from app.services.medical.ai.analysis_repository import medical_analysis_repository
from app.services.medical.ai.models import MedicalInsightReport, QuestionSuggestion
from app.services.medical.ai.question_templates import (
    is_controlled_question,
    question_source_errors,
)
from app.services.medical.visit_preparation.exceptions import VisitPreparationError
from app.services.medical.visit_preparation.repository import (
    visit_preparation_repository,
)


class VisitPreparationService:
    """Resolve report suggestions server-side before persisting user choices."""

    def __init__(
        self,
        repository=visit_preparation_repository,
        analysis_repository=medical_analysis_repository,
    ) -> None:
        self.repository = repository
        self.analysis_repository = analysis_repository

    def save_question(
        self,
        *,
        user_id: str,
        workspace_id: str,
        analysis_run_id: str,
        suggestion_id: str,
    ) -> tuple[dict[str, Any], bool, bool]:
        run = self.analysis_repository.get_run(
            analysis_run_id,
            user_id,
            workspace_id,
        )
        if not run:
            raise VisitPreparationError(
                "The medical analysis was not found.",
                code="clinician_question_analysis_not_found",
            )
        if run.get("status") != "succeeded" or run.get("validation_status") != "validated":
            raise VisitPreparationError(
                "The medical analysis is not complete.",
                code="clinician_question_analysis_unavailable",
            )
        if run.get("outdated") or not run.get("is_current"):
            raise VisitPreparationError(
                "The medical analysis is out of date. Refresh it before saving this question.",
                code="clinician_question_source_outdated",
            )

        try:
            report = MedicalInsightReport.model_validate(run.get("report"))
        except Exception as exc:
            raise VisitPreparationError(
                "The medical analysis does not contain a usable question list.",
                code="clinician_question_report_invalid",
            ) from exc

        if report.schema_version != "medical-insights-v3":
            raise VisitPreparationError(
                "Only current structured question suggestions can be saved.",
                code="clinician_question_report_outdated",
            )

        suggestion = next(
            (item for item in report.question_suggestions if item.id == suggestion_id),
            None,
        )
        if suggestion is None:
            raise VisitPreparationError(
                "The clinician question was not found in this analysis.",
                code="clinician_question_not_found",
            )
        self._validate_suggestion(suggestion, report)

        evidence_by_id = {
            str(item.get("evidence_id")): item
            for item in run.get("evidence", [])
            if isinstance(item, dict) and item.get("evidence_id")
        }
        evidence_ids = list(dict.fromkeys(suggestion.evidence_ids))
        if not evidence_ids or len(evidence_ids) > 5 or any(
            evidence_id not in evidence_by_id for evidence_id in evidence_ids
        ):
            raise VisitPreparationError(
                "The clinician question does not have complete source evidence.",
                code="clinician_question_evidence_unavailable",
            )
        if any(
            str(evidence_by_id[evidence_id].get("section_type") or "").strip().lower()
            .replace("-", "_")
            .replace(" ", "_")
            == "references"
            for evidence_id in evidence_ids
        ):
            raise VisitPreparationError(
                "Reference-list text cannot be used for a clinician question.",
                code="clinician_question_evidence_unavailable",
            )

        source = {
            "document_id": run.get("document_id"),
            "analysis_run_id": analysis_run_id,
            "parsed_source_hash": run.get("parsed_source_hash"),
            "suggestion_id": suggestion.id,
            "question": suggestion.question,
            "rationale": suggestion.rationale,
            "category": suggestion.category,
            "topic": suggestion.topic,
            "source_kind": suggestion.source_kind,
            "source_id": suggestion.source_id,
            "evidence_ids": evidence_ids,
            "language": report.language,
        }
        return self.repository.create_or_refresh_question(
            user_id=user_id,
            workspace_id=workspace_id,
            source=source,
        )

    def list_questions(self, **kwargs: Any) -> dict[str, Any]:
        return self.repository.list_questions(**kwargs)

    def update_question(self, question_id: str, **kwargs: Any) -> dict[str, Any]:
        return self.repository.update_question(question_id, **kwargs)

    def delete_question(self, question_id: str, **kwargs: Any) -> bool:
        return self.repository.delete_question(question_id, **kwargs)

    def create_visit_brief(self, **kwargs: Any) -> dict[str, Any]:
        return self.repository.create_visit_brief(**kwargs)

    def list_briefs(self, **kwargs: Any) -> dict[str, Any]:
        return self.repository.list_briefs(**kwargs)

    def get_brief(self, brief_id: str, **kwargs: Any) -> dict[str, Any] | None:
        return self.repository.get_brief(brief_id, **kwargs)

    def delete_brief(self, brief_id: str, **kwargs: Any) -> bool:
        return self.repository.delete_brief(brief_id, **kwargs)

    @staticmethod
    def _validate_suggestion(
        suggestion: QuestionSuggestion,
        report: MedicalInsightReport,
    ) -> None:
        if not suggestion.topic or not suggestion.source_kind or not suggestion.source_id:
            raise VisitPreparationError(
                "The clinician question is missing its structured source.",
                code="clinician_question_source_unavailable",
            )
        if not is_controlled_question(suggestion, report.language):
            raise VisitPreparationError(
                "The clinician question is not a server-controlled suggestion.",
                code="clinician_question_source_unavailable",
            )
        errors = question_source_errors(suggestion, report)
        if errors:
            raise VisitPreparationError(
                "The clinician question source could not be verified.",
                code="clinician_question_source_unavailable",
                details={"errors": errors},
            )


visit_preparation_service = VisitPreparationService()
