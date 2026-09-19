"""Deterministic aggregation of current medical records into a profile."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any, Iterable, Mapping


PROFILE_SECTIONS = (
    "key_findings",
    "study_methods",
    "limitations",
    "what_it_means",
    "what_it_does_not_mean",
    "applicability",
    "future_research",
    "medical_terms",
    "clinician_questions",
    "external_studies",
)

_FLAGGED_ARTICLE_STATUSES = {
    "retracted",
    "retraction_notice",
    "expression_of_concern",
    "corrected",
    "correction_notice",
}
_WITHDRAWN_ARTICLE_STATUSES = {"retracted", "retraction_notice"}
_REFERENCE_SECTIONS = {"references", "bibliography"}
_EXTERNAL_DOCUMENT_PREVIEW_LIMIT = 20


class DiseaseProfileAggregator:
    """Build a profile from repository snapshots without side effects."""

    def aggregate(
        self,
        *,
        concept_id: str,
        inputs: Iterable[Mapping[str, Any]],
        preview_limit: int = 5,
        enabled_sections: Iterable[str] | None = None,
        collect_items: bool = True,
    ) -> dict[str, Any]:
        records = [dict(item) for item in inputs]
        if not records:
            return {}

        active_sections = set(enabled_sections or PROFILE_SECTIONS)
        active_sections.intersection_update(PROFILE_SECTIONS)
        warnings: list[str] = []
        sections: dict[str, list[dict[str, Any]]] = {
            section: [] for section in PROFILE_SECTIONS
        }
        section_counts = {section: 0 for section in PROFILE_SECTIONS}
        documents = {
            str(item.get("document", {}).get("document_id")): item.get("document", {})
            for item in records
            if item.get("document", {}).get("document_id")
        }
        valid_analysis_count = 0
        expired_analysis_count = 0
        valid_analysis_ids: set[str] = set()
        valid_runs_by_id: dict[str, Mapping[str, Any]] = {}
        evidence_by_run: dict[str, dict[str, dict[str, Any]]] = {}
        all_question_count = 0
        stats = {
            "research_paper_count": 0,
            "guideline_count": 0,
            "other_medical_document_count": 0,
            "valid_analysis_count": 0,
            "expired_analysis_count": 0,
            "external_article_count": 0,
            "flagged_article_count": 0,
            "comparator_reported_count": 0,
            "comparator_not_reported_count": 0,
            "human_study_count": 0,
            "animal_study_count": 0,
            "in_vitro_study_count": 0,
            "unknown_study_population_count": 0,
            "sample_size_reported_count": 0,
            "sample_size_not_reported_count": 0,
            "unknown_date_count": 0,
        }

        for document in documents.values():
            kind = str(document.get("document_kind") or "other_medical")
            if kind == "research_paper":
                stats["research_paper_count"] += 1
            elif kind == "guideline":
                stats["guideline_count"] += 1
            else:
                stats["other_medical_document_count"] += 1
            if not str(document.get("document_date") or "").strip():
                stats["unknown_date_count"] += 1

        for record in records:
            document = record.get("document") or {}
            document_id = str(document.get("document_id") or "")
            analyses = record.get("analyses") or []
            if not isinstance(analyses, list):
                analyses = []
            for analysis in analyses:
                if not isinstance(analysis, Mapping):
                    continue
                run = analysis.get("run") or {}
                run_id = str(run.get("run_id") or "")
                if (
                    run.get("status") == "succeeded"
                    and run.get("validation_status") == "validated"
                    and not analysis.get("valid")
                ):
                    expired_analysis_count += 1
                if not analysis.get("valid"):
                    if analysis.get("warnings"):
                        warnings.extend(_strings(analysis["warnings"]))
                    continue
                report = analysis.get("report")
                if not isinstance(report, Mapping) or not run_id:
                    warnings.append("analysis_report_unavailable")
                    continue
                valid_analysis_count += 1
                valid_analysis_ids.add(run_id)
                valid_runs_by_id[run_id] = run
                evidence_by_run[run_id] = _evidence_index(analysis.get("evidence"))
                self._add_report_sections(
                    sections=sections,
                    warnings=warnings,
                    report=report,
                    document=document,
                    run=run,
                    evidence=evidence_by_run[run_id],
                    enabled_sections=active_sections,
                    collect_items=collect_items,
                    section_counts=section_counts,
                )
                self._add_method_stats(stats, report)

            questions = record.get("questions") or []
            if "clinician_questions" not in active_sections:
                questions = []
            if isinstance(questions, list):
                for question in questions:
                    if not isinstance(question, Mapping):
                        continue
                    run_id = str(question.get("analysis_run_id") or "")
                    if run_id not in valid_analysis_ids:
                        continue
                    evidence = evidence_by_run.get(run_id, {})
                    current_run = valid_runs_by_id.get(run_id)
                    evidence_ids = _unique_strings(question.get("evidence_ids"))[:5]
                    sources = _document_sources(
                        evidence_ids,
                        evidence,
                        document,
                        run_id,
                        str((current_run or {}).get("parsed_source_hash") or ""),
                        warnings,
                    )
                    if not sources:
                        continue
                    section_counts["clinician_questions"] += 1
                    if collect_items:
                        sections["clinician_questions"].append(
                            {
                                "id": f"{document_id}:{run_id}:question:{question.get('id')}",
                                "item_type": "question",
                                "section": "clinician_questions",
                                "document_id": document_id,
                                "document_title": document.get("title", ""),
                                "document_kind": document.get("document_kind", ""),
                                "document_date": document.get("document_date", ""),
                                "analysis_run_id": run_id,
                                "parsed_source_hash": str(
                                    (current_run or {}).get("parsed_source_hash") or ""
                                ),
                                "source_status": "current",
                                "question": str(question.get("question") or ""),
                                "rationale": str(question.get("rationale") or ""),
                                "category": str(question.get("category") or ""),
                                "topic": str(question.get("topic") or ""),
                                "source_kind": str(question.get("source_kind") or ""),
                                "source_id": str(question.get("source_id") or ""),
                                "evidence_ids": evidence_ids,
                                "evidence": sources,
                            }
                        )
                    all_question_count += 1

        external_stats = (0, 0)
        if "external_studies" in active_sections:
            external_stats = self._add_external_studies(
                sections=sections,
                records=records,
                valid_analysis_ids=valid_analysis_ids,
                warnings=warnings,
                collect_items=collect_items,
                section_counts=section_counts,
            )

        for section in PROFILE_SECTIONS:
            sections[section] = sorted(
                sections[section], key=_item_sort_key
            )

        unique_warnings = _unique_strings(warnings)[:20]
        concept_values = [
            item.get("link") or {}
            for item in records
            if isinstance(item.get("link"), Mapping)
        ]
        first_link = concept_values[0] if concept_values else {}
        last_updated = _latest_timestamp(
            value
            for record in records
            for value in (
                (record.get("link") or {}).get("updated_at"),
                (record.get("document") or {}).get("modified_at"),
                *[
                    (analysis.get("run") or {}).get("updated_at")
                    for analysis in (record.get("analyses") or [])
                    if isinstance(analysis, Mapping)
                ],
            )
        )
        stats["valid_analysis_count"] = valid_analysis_count
        stats["expired_analysis_count"] = expired_analysis_count
        stats["external_article_count"], stats["flagged_article_count"] = external_stats
        stats["document_count"] = len(documents)
        document_views = _document_views(records, documents)

        return {
            "concept_id": concept_id,
            "preferred_name_en": str(first_link.get("preferred_name_en") or ""),
            "preferred_name_zh": str(first_link.get("preferred_name_zh") or ""),
            "ontology_version": _common_value(
                concept_values, "ontology_version", default=""
            ),
            "document_count": len(documents),
            "analysis_count": valid_analysis_count,
            "external_article_count": stats["external_article_count"],
            "saved_question_count": all_question_count,
            "last_updated_at": last_updated,
            "documents": document_views,
            "section_counts": section_counts,
            "stats": stats,
            "sections": {
                section: sections[section][: max(0, min(int(preview_limit), 50))]
                for section in PROFILE_SECTIONS
            },
            # The service consumes this in-memory view for cursor paging and
            # removes it before validating the public response model.
            "_all_sections": sections if collect_items else {},
            "warnings": unique_warnings,
        }

    def aggregate_summary(
        self,
        *,
        concept_id: str,
        inputs: Iterable[Mapping[str, Any]],
    ) -> dict[str, Any]:
        """Build counts and health metadata without retaining item payloads."""
        return self.aggregate(
            concept_id=concept_id,
            inputs=inputs,
            preview_limit=0,
            collect_items=False,
        )

    def aggregate_detail(
        self,
        *,
        concept_id: str,
        inputs: Iterable[Mapping[str, Any]],
        preview_limit: int = 5,
    ) -> dict[str, Any]:
        """Build the bounded detail preview for one disease profile."""
        return self.aggregate(
            concept_id=concept_id,
            inputs=inputs,
            preview_limit=preview_limit,
        )

    def aggregate_section(
        self,
        *,
        concept_id: str,
        inputs: Iterable[Mapping[str, Any]],
        section: str,
    ) -> dict[str, Any]:
        """Build only one public section while retaining its count metadata."""
        return self.aggregate(
            concept_id=concept_id,
            inputs=inputs,
            preview_limit=0,
            enabled_sections={section},
        )

    def _add_report_sections(
        self,
        *,
        sections: dict[str, list[dict[str, Any]]],
        warnings: list[str],
        report: Mapping[str, Any],
        document: Mapping[str, Any],
        run: Mapping[str, Any],
        evidence: Mapping[str, Mapping[str, Any]],
        enabled_sections: set[str],
        collect_items: bool,
        section_counts: dict[str, int],
    ) -> None:
        run_id = str(run.get("run_id") or "")
        for section in (
            "key_findings",
            "limitations",
            "what_it_means",
            "what_it_does_not_mean",
            "applicability",
            "future_research",
        ):
            if section not in enabled_sections:
                continue
            values = report.get(section)
            if not isinstance(values, list):
                continue
            for index, value in enumerate(values):
                if not isinstance(value, Mapping):
                    continue
                statement = str(value.get("statement") or "").strip()
                explanation = str(value.get("plain_explanation") or "").strip()
                evidence_ids = _unique_strings(value.get("evidence_ids"))[:5]
                sources = _document_sources(
                    evidence_ids,
                    evidence,
                    document,
                    run_id,
                    str(run.get("parsed_source_hash") or ""),
                    warnings,
                )
                if not statement or not sources:
                    continue
                section_counts[section] += 1
                if collect_items:
                    sections[section].append(
                        _finding_item(
                            section=section,
                            document=document,
                            run=run,
                            item_id=f"{run_id}:{section}:{value.get('id') or index}",
                            text=statement,
                            explanation=explanation,
                            evidence_ids=evidence_ids,
                            sources=sources,
                            interpretation_type=str(value.get("interpretation_type") or ""),
                        )
                    )

        methods = report.get("study_methods")
        if "study_methods" in enabled_sections and isinstance(methods, Mapping):
            for field in (
                "design",
                "population",
                "human_animal_in_vitro",
                "sample_size",
                "comparator",
            ):
                value = methods.get(field)
                if not isinstance(value, Mapping):
                    continue
                support_status = str(value.get("support_status") or "uncertain")
                item_value = str(value.get("value") or "").strip()
                evidence_ids = _unique_strings(value.get("evidence_ids"))[:5]
                sources = _document_sources(
                    evidence_ids,
                    evidence,
                    document,
                    run_id,
                    str(run.get("parsed_source_hash") or ""),
                    warnings,
                )
                # "Not reported" is an explicit report state, not a guessed
                # value, so it remains visible without inventing a quote.
                if support_status == "not_reported":
                    # Do not trust a stale or malformed provider value when
                    # it claims that the source did not report the field.
                    item_value = "Not reported in the source analysis."
                    evidence_ids = []
                    sources = []
                elif not item_value or not sources:
                    continue
                section_counts["study_methods"] += 1
                if collect_items:
                    sections["study_methods"].append(
                        {
                            **_base_item(
                                section="study_methods",
                                document=document,
                                run=run,
                                item_id=f"{run_id}:study_methods:{field}",
                                item_type="attribute",
                                evidence_ids=evidence_ids,
                                sources=sources,
                            ),
                            "title": field.replace("_", " ").title(),
                            "value": item_value,
                            "support_status": support_status,
                        }
                    )

        terms = report.get("medical_terms")
        if "medical_terms" in enabled_sections and isinstance(terms, list):
            for index, value in enumerate(terms):
                if not isinstance(value, Mapping):
                    continue
                term = str(value.get("term") or "").strip()
                explanation = str(value.get("explanation") or "").strip()
                evidence_ids = _unique_strings(value.get("evidence_ids"))[:5]
                sources = _document_sources(
                    evidence_ids,
                    evidence,
                    document,
                    run_id,
                    str(run.get("parsed_source_hash") or ""),
                    warnings,
                )
                if not term or not explanation or not sources:
                    continue
                section_counts["medical_terms"] += 1
                if collect_items:
                    sections["medical_terms"].append(
                        {
                            **_base_item(
                                section="medical_terms",
                                document=document,
                                run=run,
                                item_id=f"{run_id}:medical_terms:{index}",
                                item_type="term",
                                evidence_ids=evidence_ids,
                                sources=sources,
                            ),
                            "term": term,
                            "explanation": explanation,
                        }
                    )

    def _add_method_stats(self, stats: dict[str, int], report: Mapping[str, Any]) -> None:
        methods = report.get("study_methods")
        if not isinstance(methods, Mapping):
            stats["unknown_study_population_count"] += 1
            stats["comparator_not_reported_count"] += 1
            stats["sample_size_not_reported_count"] += 1
            return
        comparator = methods.get("comparator")
        if _reported_attribute(comparator):
            stats["comparator_reported_count"] += 1
        else:
            stats["comparator_not_reported_count"] += 1
        sample_size = methods.get("sample_size")
        if _reported_attribute(sample_size):
            stats["sample_size_reported_count"] += 1
        else:
            stats["sample_size_not_reported_count"] += 1

        population = str(
            (methods.get("human_animal_in_vitro") or {}).get("value")
            if isinstance(methods.get("human_animal_in_vitro"), Mapping)
            else ""
        ).casefold()
        if any(term in population for term in ("animal", "mouse", "mice", "rat", "动物", "小鼠")):
            stats["animal_study_count"] += 1
        elif any(term in population for term in ("in vitro", "cell", "细胞", "体外")):
            stats["in_vitro_study_count"] += 1
        elif any(term in population for term in ("human", "patient", "people", "人体", "患者", "人群")):
            stats["human_study_count"] += 1
        else:
            stats["unknown_study_population_count"] += 1

    def _add_external_studies(
        self,
        *,
        sections: dict[str, list[dict[str, Any]]],
        records: list[dict[str, Any]],
        valid_analysis_ids: set[str],
        warnings: list[str],
        collect_items: bool,
        section_counts: dict[str, int],
    ) -> tuple[int, int]:
        by_key: dict[tuple[str, str], dict[str, Any]] = {}
        for record in records:
            document = record.get("document") or {}
            document_id = str(document.get("document_id") or "")
            for match in record.get("matches") or []:
                if not isinstance(match, Mapping):
                    continue
                if str(match.get("analysis_run_id") or "") not in valid_analysis_ids:
                    continue
                article = match.get("article")
                if not isinstance(article, Mapping):
                    continue
                source = str(article.get("source") or "").strip().lower()
                external_id = str(article.get("external_id") or "").strip()
                if not source or not external_id:
                    warnings.append("external_article_identifier_missing")
                    continue
                key = (source, external_id)
                status = str(article.get("retraction_status") or "unknown").strip().lower()
                flagged = status in _FLAGGED_ARTICLE_STATUSES
                current = by_key.get(key)
                if current is None:
                    current = {
                        "id": f"external:{source}:{external_id}",
                        "item_type": "article",
                        "section": "external_studies",
                        "document_ids": [document_id] if document_id else [],
                        "document_titles": [document.get("title", "")] if document_id else [],
                        "related_document_count": 1 if document_id else 0,
                        "related_documents_truncated": False,
                        "_related_document_ids": {document_id} if document_id else set(),
                        "document_title": document.get("title", ""),
                        "document_kind": document.get("document_kind", ""),
                        "document_date": document.get("document_date", ""),
                        "analysis_run_id": match.get("analysis_run_id"),
                        "source_status": "current",
                        "title": str(article.get("title") or ""),
                        "source": source,
                        "external_id": external_id,
                        "doi": article.get("doi"),
                        "pmcid": article.get("pmcid"),
                        "journal": str(article.get("journal") or ""),
                        "publication_date": article.get("publication_date"),
                        "publication_year": article.get("publication_year"),
                        "publication_types": _list(article.get("publication_types")),
                        "source_url": str(article.get("source_url") or ""),
                        "retraction_status": status,
                        "flagged": flagged,
                        "warnings": [],
                        "relevance_score": match.get("relevance_score"),
                        "match_specificity": str(match.get("match_specificity") or ""),
                        "evidence": [
                            {
                                "source_type": "external_article",
                                "source": source,
                                "external_id": external_id,
                                "source_url": str(article.get("source_url") or ""),
                                "retraction_status": status,
                                "flagged": flagged,
                                "warnings": [],
                            }
                        ],
                    }
                    by_key[key] = current
                else:
                    related_ids = current["_related_document_ids"]
                    if document_id and document_id not in related_ids:
                        related_ids.add(document_id)
                        current["related_document_count"] += 1
                        if len(current["document_ids"]) < _EXTERNAL_DOCUMENT_PREVIEW_LIMIT:
                            current["document_ids"].append(document_id)
                        else:
                            current["related_documents_truncated"] = True
                        title = str(document.get("title") or "")
                        if title and len(current["document_titles"]) < _EXTERNAL_DOCUMENT_PREVIEW_LIMIT:
                            current["document_titles"].append(title)
                    current["flagged"] = bool(current["flagged"] or flagged)
                    if _article_status_priority(status) > _article_status_priority(
                        current["retraction_status"]
                    ):
                        current["retraction_status"] = status
                        current["flagged"] = status in _FLAGGED_ARTICLE_STATUSES
                        if current["evidence"]:
                            current["evidence"][0]["retraction_status"] = status
                            current["evidence"][0]["flagged"] = current["flagged"]
                if status in _WITHDRAWN_ARTICLE_STATUSES:
                    warning = "This external article is marked as withdrawn."
                    if warning not in current["warnings"]:
                        current["warnings"].append(warning)
                    warnings.append("retracted_external_article_present")
                elif status == "expression_of_concern":
                    warning = "This external article has an expression of concern."
                    if warning not in current["warnings"]:
                        current["warnings"].append(warning)
                elif status in {"corrected", "correction_notice"}:
                    warning = "This external article has a correction notice."
                    if warning not in current["warnings"]:
                        current["warnings"].append(warning)
        for item in by_key.values():
            item.pop("_related_document_ids", None)

        article_count = sum(
            1
            for item in by_key.values()
            if str(item.get("retraction_status") or "unknown")
            not in _WITHDRAWN_ARTICLE_STATUSES
        )
        flagged_count = sum(1 for item in by_key.values() if item.get("flagged"))
        section_counts["external_studies"] = len(by_key)
        if collect_items:
            sections["external_studies"].extend(by_key.values())
        return article_count, flagged_count


def _document_views(
    records: list[Mapping[str, Any]],
    documents: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Expose only safe document snapshots, while retaining source health."""
    by_document: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for record in records:
        document = record.get("document")
        if isinstance(document, Mapping) and document.get("document_id"):
            by_document[str(document["document_id"])].append(record)

    result: list[dict[str, Any]] = []
    for document_id, document in documents.items():
        analyses = [
            analysis
            for record in by_document.get(document_id, [])
            for analysis in (record.get("analyses") or [])
            if isinstance(analysis, Mapping)
        ]
        if any(analysis.get("valid") for analysis in analyses):
            source_status = "current"
        elif any(
            str((analysis.get("run") or {}).get("status") or "") == "succeeded"
            for analysis in analyses
        ):
            source_status = "outdated"
        else:
            source_status = "unavailable"
        document_warnings = _unique_strings(
            [
                warning
                for analysis in analyses
                for warning in _strings(analysis.get("warnings"))
            ]
        )[:20]
        result.append(
            {
                "document_id": document_id,
                "title": str(document.get("title") or "Untitled document"),
                "document_kind": str(document.get("document_kind") or "unknown"),
                "language": str(document.get("language") or "unknown"),
                "document_date": str(document.get("document_date") or ""),
                "parsed_source_hash": str(document.get("parsed_source_hash") or ""),
                "source_status": source_status,
                "warnings": document_warnings,
            }
        )
    return sorted(result, key=_item_sort_key)


def _base_item(
    *,
    section: str,
    document: Mapping[str, Any],
    run: Mapping[str, Any],
    item_id: str,
    item_type: str,
    evidence_ids: list[str],
    sources: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "id": item_id,
        "item_type": item_type,
        "section": section,
        "document_id": document.get("document_id"),
        "document_ids": [document.get("document_id")],
        "document_title": document.get("title", ""),
        "document_titles": [document.get("title", "")],
        "document_kind": document.get("document_kind", ""),
        "document_date": document.get("document_date", ""),
        "analysis_run_id": run.get("run_id"),
        "parsed_source_hash": run.get("parsed_source_hash", ""),
        "source_status": "current",
        "evidence_ids": evidence_ids,
        "evidence": sources,
    }


def _finding_item(
    *,
    section: str,
    document: Mapping[str, Any],
    run: Mapping[str, Any],
    item_id: str,
    text: str,
    explanation: str,
    evidence_ids: list[str],
    sources: list[dict[str, Any]],
    interpretation_type: str,
) -> dict[str, Any]:
    return {
        **_base_item(
            section=section,
            document=document,
            run=run,
            item_id=item_id,
            item_type="finding",
            evidence_ids=evidence_ids,
            sources=sources,
        ),
        "text": text,
        "explanation": explanation,
        "title": interpretation_type,
    }


def _document_sources(
    evidence_ids: list[str],
    evidence: Mapping[str, Mapping[str, Any]],
    document: Mapping[str, Any],
    run_id: str,
    parsed_source_hash: str,
    warnings: list[str],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for evidence_id in evidence_ids:
        item = evidence.get(evidence_id)
        if not item:
            warnings.append("profile_evidence_unavailable")
            continue
        section_type = str(item.get("section_type") or "unknown").strip().lower()
        if section_type in _REFERENCE_SECTIONS:
            warnings.append("profile_reference_evidence_excluded")
            continue
        result.append(
            {
                "source_type": "document_evidence",
                "evidence_id": evidence_id,
                "document_id": document.get("document_id"),
                "document_title": document.get("title", ""),
                "document_date": document.get("document_date", ""),
                "analysis_run_id": run_id,
                "parsed_source_hash": parsed_source_hash,
                "section_type": item.get("section_type") or "unknown",
                "section_title": item.get("section_title") or "",
                "page_start": item.get("page_start"),
                "page_end": item.get("page_end"),
                "quote": item.get("quote") or "",
                "warnings": [],
            }
        )
    return result[:5]


def _evidence_index(value: Any) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    if not isinstance(value, list):
        return result
    for item in value:
        if not isinstance(item, Mapping):
            continue
        for key in (item.get("id"), item.get("evidence_id")):
            if key:
                result[str(key)] = dict(item)
    return result


def _reported_attribute(value: Any) -> bool:
    if not isinstance(value, Mapping):
        return False
    if str(value.get("support_status") or "") == "not_reported":
        return False
    return bool(str(value.get("value") or "").strip())


def _item_sort_key(item: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        str(item.get("document_date") or "9999-99-99"),
        str(item.get("title") or item.get("document_title") or "").casefold(),
        str(item.get("id") or ""),
    )


def _article_status_priority(status: str) -> int:
    return {
        "retracted": 5,
        "retraction_notice": 4,
        "expression_of_concern": 3,
        "corrected": 2,
        "correction_notice": 2,
        "unknown": 1,
        "normal": 0,
    }.get(status, 1)


def _common_value(values: list[Mapping[str, Any]], key: str, *, default: str) -> str:
    for value in values:
        item = str(value.get(key) or "").strip()
        if item:
            return item
    return default


def _latest_timestamp(values: Iterable[Any]) -> str:
    candidates = [str(value).strip() for value in values if str(value or "").strip()]
    if not candidates:
        return ""
    try:
        return max(candidates, key=lambda value: datetime.fromisoformat(value))
    except ValueError:
        return max(candidates)


def _unique_strings(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = str(item or "").strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _strings(value: Any) -> list[str]:
    if isinstance(value, (list, tuple)):
        return _unique_strings(value)
    return [str(value).strip()] if str(value or "").strip() else []


def _list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item or "").strip()]
