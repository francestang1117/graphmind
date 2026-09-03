"""Run medical classification and paper structure analysis."""

from __future__ import annotations

import logging
from typing import Any, Optional

from app.services.medical.document_classifier import MedicalDocumentClassifier
from app.services.medical.models import MedicalDocumentAnalysis, MedicalDocumentKind
from app.services.medical.paper_structure_parser import PaperStructureParser
from app.services.medical.repository import MedicalRepository, medical_repository

log = logging.getLogger(__name__)

_classifier = MedicalDocumentClassifier()
_paper_parser = PaperStructureParser()


def analyze_document(
    parsed: dict[str, Any],
    *,
    filename: str = "",
    original_filename: str = "",
    document_id: str = "",
    user_id: str = "local-dev",
    workspace_id: Optional[str] = None,
    repository: MedicalRepository = medical_repository,
) -> dict[str, Any]:
    """Add medical metadata to a generic parser result.

    The generic parser remains the source of truth for ordinary files. Medical
    parsing only replaces chunks when the document looks like a paper.
    """
    metadata = parsed.setdefault("metadata", {})
    parser_version = str(
        metadata.get("parser_version")
        or f"document-parser-{metadata.get('parser') or 'unified-v1'}"
    )
    metadata["parser_version"] = parser_version

    try:
        analysis = _classifier.classify(
            parsed,
            filename=filename,
            original_filename=original_filename,
        )
    except Exception as exc:  # classification must not stop ordinary indexing
        log.warning("Medical classification failed for %s: %s", filename, exc)
        analysis = MedicalDocumentAnalysis(
            document_kind=MedicalDocumentKind.UNKNOWN.value,
            confidence=0.0,
            language="unknown",
            classifier_version=MedicalDocumentClassifier.VERSION,
            warnings=["classification_failed"],
        )

    analysis_dict = analysis.to_dict()
    structured_sections: list[dict[str, Any]] = []

    if analysis.document_kind == MedicalDocumentKind.RESEARCH_PAPER.value:
        try:
            structure = _paper_parser.parse(parsed, analysis)
            structured_sections = [section.to_dict() for section in structure.sections]
            if structure.chunks:
                # These chunks carry page and section metadata used by search
                # and later evidence citations.
                parsed["chunks"] = structure.chunks
            analysis_dict["missing_sections"] = structure.missing_sections
            analysis_dict["warnings"] = _unique(
                [*analysis_dict.get("warnings", []), *structure.warnings]
            )
        except Exception as exc:  # keep the old chunks if paper parsing fails
            log.warning("Paper structure parsing failed for %s: %s", filename, exc)
            analysis_dict["warnings"] = _unique(
                [*analysis_dict.get("warnings", []), "structure_parse_failed"]
            )

    analysis_dict["parser_version"] = parser_version
    analysis_dict["sections"] = structured_sections
    metadata.update(
        {
            "document_kind": analysis_dict["document_kind"],
            "source_kind": metadata.get("source_kind") or "user_upload",
            "language": analysis_dict["language"],
            "parser_version": parser_version,
            "medical_classifier_version": analysis_dict["classifier_version"],
            "medical_signals": analysis_dict.get("signals", []),
            "medical_warnings": analysis_dict.get("warnings", []),
            "missing_sections": analysis_dict.get("missing_sections", []),
            "medical_section_count": len(structured_sections),
        }
    )
    parsed["medical_analysis"] = analysis_dict

    if document_id:
        try:
            repository.replace_analysis(
                document_id,
                analysis_dict,
                structured_sections,
                user_id=user_id,
                workspace_id=workspace_id,
            )
        except Exception as exc:  # repository errors should not break indexing
            log.warning("Could not persist medical analysis for %s: %s", filename, exc)

    return analysis_dict


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(str(value) for value in values if value))
