"""Select source chunks for one analysis and attach stable evidence ids."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable

from app.services.medical.text_quality import assess_passage


_REFERENCE_SECTION_TYPES = frozenset(
    {
        "references",
        "reference",
        "bibliography",
        "works_cited",
        "reference_list",
        "references_and_bibliography",
    }
)
_NON_MEDICAL_SECTION_TYPES = _REFERENCE_SECTION_TYPES | frozenset(
    {
        "supplementary",
        "acknowledgements",
        "acknowledgments",
        "funding",
        "author_contributions",
        "conflicts_of_interest",
        "figure_caption",
        "table_caption",
        "header",
        "footer",
        "metadata",
        "title_page",
    }
)


@dataclass(frozen=True)
class EvidenceItem:
    evidence_id: str
    chunk_id: str
    section_id: str | None
    section_type: str
    section_title: str
    page_start: int | None
    page_end: int | None
    character_start: int | None
    character_end: int | None
    text: str
    token_count: int
    source_index: int
    truncated: bool = False
    quality_score: int = 100
    quality_flags: tuple[str, ...] = ()


@dataclass
class AnalysisContext:
    title: str
    document_kind: str
    language: str
    evidence: list[EvidenceItem] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    total_chunks: int = 0
    source_chunks_total: int = 0
    eligible_chunks: int = 0
    quality_filtered_chunks: int = 0
    scope_excluded_chunks: int = 0
    duplicate_chunks: int = 0
    budget_excluded_chunks: int = 0
    total_tokens: int = 0
    max_input_tokens: int = 0
    included_sections: list[str] = field(default_factory=list)
    omitted_sections: list[str] = field(default_factory=list)

    @property
    def coverage_complete(self) -> bool:
        return (
            not self.omitted_sections
            and len(self.evidence) >= self.total_chunks
            and not any(item.truncated for item in self.evidence)
        )

    @property
    def evidence_by_id(self) -> dict[str, EvidenceItem]:
        return {item.evidence_id: item for item in self.evidence}

    def render(self) -> str:
        """Render only the selected evidence blocks for the provider prompt."""
        blocks = [
            f"Document title: {self.title}\n"
            f"Document kind: {self.document_kind}\n"
            f"Language: {self.language}"
        ]
        for item in self.evidence:
            page = _page_label(item.page_start, item.page_end)
            section = item.section_type or "unknown"
            title = item.section_title or ""
            location = (
                f"[{item.evidence_id}] section={section} title={title!r} "
                f"page={page} chars={item.character_start}:{item.character_end}"
            )
            blocks.append(f"{location}\n{item.text}")
        return "\n\n".join(blocks)


class ContextBuilder:
    """Build a bounded, page-aware context from persisted parser chunks."""

    PRIORITY = {
        "results": 0,
        "recommendations": 0,
        "evidence": 0,
        "contraindications": 0,
        "limitations": 1,
        "adverse_events": 1,
        "monitoring": 1,
        "conclusion": 2,
        "abstract": 3,
        "scope": 3,
        "population": 4,
        "intervention": 4,
        "comparator": 4,
        "outcomes": 4,
        "methods": 5,
        "discussion": 6,
        "implementation": 5,
        "introduction": 7,
        "title": 8,
        "unknown": 9,
        "references": 20,
        "reference": 20,
        "bibliography": 20,
        "works_cited": 20,
        "reference_list": 20,
        "references_and_bibliography": 20,
        "supplementary": 15,
    }

    def build(
        self,
        chunks: Iterable[dict[str, Any]],
        *,
        sections: Iterable[dict[str, Any]] | None = None,
        source_warnings: Iterable[str] | None = None,
        title: str = "",
        document_kind: str = "unknown",
        language: str = "unknown",
        max_input_tokens: int = 12000,
        redact_pii: bool = True,
    ) -> AnalysisContext:
        section_map = self._section_map(sections or [])
        candidates: list[tuple[int, int, dict[str, Any]]] = []
        seen: set[tuple[str, str]] = set()
        source_chunks_total = 0
        quality_filtered_chunks = 0
        scope_excluded_chunks = 0
        duplicate_chunks = 0

        safe_title = title or "Untitled medical document"
        title_redacted = False
        if redact_pii:
            safe_title, title_redacted = redact_sensitive_fields(safe_title)

        for index, raw_chunk in enumerate(chunks):
            if not isinstance(raw_chunk, dict):
                continue
            source_chunks_total += 1
            text = str(raw_chunk.get("text") or "").strip()
            if not text:
                scope_excluded_chunks += 1
                continue
            metadata = raw_chunk.get("metadata")
            metadata = metadata if isinstance(metadata, dict) else {}
            if metadata.get("medical_evidence") is False:
                scope_excluded_chunks += 1
                continue
            section_type = self._section_type(raw_chunk, metadata)
            section = self._section_for(raw_chunk, metadata, section_type, section_map)
            if section_type == "unknown":
                # Some older rows only keep the section id. The section row
                # still has enough information to restore its label here.
                section_type = self._section_type(
                    section,
                    section.get("metadata") if isinstance(section.get("metadata"), dict) else {},
                )
            if section_type in _NON_MEDICAL_SECTION_TYPES:
                # These sections remain available in the document browser,
                # but acknowledgements and bibliographic material are not
                # medical evidence for a report.
                scope_excluded_chunks += 1
                continue
            section_title = str(
                raw_chunk.get("section_title")
                or metadata.get("section_title")
                or metadata.get("section")
                or section.get("original_title")
                or ""
            )
            quality = assess_passage(
                text,
                section_type=section_type,
                section_title=section_title,
                metadata={
                    **metadata,
                    "quality_flags": [
                        *(metadata.get("quality_flags") or []),
                        *(metadata.get("pdf_quality_flags") or []),
                    ],
                },
                source_warnings=source_warnings or (),
            )
            if not quality.usable:
                quality_filtered_chunks += 1
                continue
            chunk_id = str(raw_chunk.get("id") or f"chunk:{index}")
            dedupe_key = (chunk_id, text)
            if dedupe_key in seen:
                duplicate_chunks += 1
                continue
            seen.add(dedupe_key)
            normalized = {
                "raw": raw_chunk,
                "metadata": metadata,
                "text": text,
                "token_count": _estimate_tokens(text),
                "section_type": section_type,
                "section": section,
                "index": index,
                "quality": quality,
            }
            candidates.append((self.PRIORITY.get(section_type, 10), index, normalized))

        candidates.sort(key=lambda value: (value[0], value[1]))
        budget = max(1, int(max_input_tokens or 1))
        warnings = _warning_codes(source_warnings or [])
        redacted = title_redacted
        total_tokens = sum(candidate[2]["token_count"] for candidate in candidates)
        allowances: dict[int, int] = {}
        remaining = budget

        if total_tokens <= budget:
            allowances = {
                candidate["index"]: candidate["token_count"]
                for _priority, _index, candidate in candidates
            }
            remaining -= total_tokens
        else:
            # Reserve one share for each useful section, then spend the rest
            # by priority. A later pass can extend a partially selected chunk.
            first_by_section: dict[str, dict[str, Any]] = {}
            for _priority, _index, candidate in candidates:
                section_type = candidate["section_type"]
                if section_type in _NON_MEDICAL_SECTION_TYPES:
                    continue
                first_by_section.setdefault(section_type, candidate)
            section_candidates = list(first_by_section.values())
            for position, candidate in enumerate(section_candidates):
                if remaining <= 0:
                    break
                sections_left = len(section_candidates) - position
                share = max(1, remaining // max(1, sections_left))
                granted = min(candidate["token_count"], share, remaining)
                allowances[candidate["index"]] = granted
                remaining -= granted

            for _priority, _index, candidate in candidates:
                if remaining <= 0:
                    break
                current = allowances.get(candidate["index"], 0)
                granted = min(candidate["token_count"] - current, remaining)
                if granted > 0:
                    allowances[candidate["index"]] = current + granted
                    remaining -= granted

        selected: list[EvidenceItem] = []
        for _priority, index, candidate in candidates:
            allowed = allowances.get(index, 0)
            if allowed <= 0:
                continue
            item_truncated = candidate["token_count"] > allowed
            text = (
                _truncate_text(candidate["text"], allowed)
                if item_truncated
                else candidate["text"]
            )
            if redact_pii:
                text, changed = redact_sensitive_fields(text)
                redacted = redacted or changed

            raw = candidate["raw"]
            metadata = candidate["metadata"]
            section = candidate["section"]
            section_title = str(
                raw.get("section_title")
                or metadata.get("section_title")
                or metadata.get("section")
                or section.get("original_title")
                or ""
            )
            if redact_pii:
                section_title, changed = redact_sensitive_fields(section_title)
                redacted = redacted or changed
            selected.append(
                EvidenceItem(
                    evidence_id="",
                    chunk_id=str(raw.get("id") or f"chunk:{index}"),
                    section_id=_as_optional_str(
                        raw.get("section_id") or metadata.get("section_id") or section.get("id")
                    ),
                    section_type=candidate["section_type"],
                    section_title=section_title,
                    page_start=_as_int(
                        _first_present(
                            raw.get("page_start"), metadata.get("page_start"), raw.get("page"),
                            metadata.get("page"), section.get("page_start"),
                        )
                    ),
                    page_end=_as_int(
                        _first_present(
                            raw.get("page_end"), metadata.get("page_end"), raw.get("page"),
                            metadata.get("page"), section.get("page_end"),
                        )
                    ),
                    character_start=_as_int(
                        _first_present(
                            raw.get("char_start"), metadata.get("char_start"), raw.get("start"),
                            metadata.get("start"),
                        )
                    ),
                    character_end=_as_int(
                        _first_present(
                            raw.get("char_end"), metadata.get("char_end"), raw.get("end"),
                            metadata.get("end"),
                        )
                    ),
                    text=text,
                    token_count=_estimate_tokens(text),
                    source_index=index,
                    truncated=item_truncated,
                    quality_score=candidate["quality"].score,
                    quality_flags=candidate["quality"].reasons,
                )
            )

        selected.sort(key=lambda item: item.source_index)
        # Evidence ids follow source order in the prompt, which makes the UI
        # easier to scan and keeps references stable for one run.
        selected = [
            EvidenceItem(
                evidence_id=f"EVIDENCE_{index:03d}",
                chunk_id=item.chunk_id,
                section_id=item.section_id,
                section_type=item.section_type,
                section_title=item.section_title,
                page_start=item.page_start,
                page_end=item.page_end,
                character_start=item.character_start,
                character_end=item.character_end,
                text=item.text,
                token_count=item.token_count,
                source_index=item.source_index,
                truncated=item.truncated,
                quality_score=item.quality_score,
                quality_flags=item.quality_flags,
            )
            for index, item in enumerate(selected, start=1)
        ]

        budget_excluded_chunks = sum(
            1 for _priority, _index, candidate in candidates
            if allowances.get(candidate["index"], 0) <= 0
        )

        if redacted:
            warnings.append("pii_redacted")
        if any(item.truncated for item in selected) or len(selected) < len(candidates):
            warnings.append("context_truncated")
        if quality_filtered_chunks:
            warnings.append("evidence_quality_filtered")
        all_sections = list(dict.fromkeys(candidate[2]["section_type"] for candidate in candidates))
        included_sections = list(dict.fromkeys(item.section_type for item in selected))
        omitted_sections = [value for value in all_sections if value not in included_sections]
        if omitted_sections:
            warnings.append("sections_omitted")
        return AnalysisContext(
            title=safe_title,
            document_kind=document_kind or "unknown",
            language=language or "unknown",
            evidence=selected,
            warnings=warnings,
            total_chunks=len(candidates),
            source_chunks_total=source_chunks_total,
            eligible_chunks=len(candidates),
            quality_filtered_chunks=quality_filtered_chunks,
            scope_excluded_chunks=scope_excluded_chunks,
            duplicate_chunks=duplicate_chunks,
            budget_excluded_chunks=budget_excluded_chunks,
            total_tokens=total_tokens,
            max_input_tokens=budget,
            included_sections=included_sections,
            omitted_sections=omitted_sections,
        )

    def _section_map(self, sections: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for section in sections:
            if not isinstance(section, dict):
                continue
            ordinal = section.get("ordinal")
            if ordinal is not None:
                result[str(ordinal)] = section
            if section.get("id"):
                result[str(section["id"])] = section
        return result

    def _section_for(
        self,
        chunk: dict[str, Any],
        metadata: dict[str, Any],
        section_type: str,
        section_map: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        key = chunk.get("section_id") or metadata.get("section_id")
        if key is None:
            key = chunk.get("section_ordinal") or metadata.get("section_ordinal")
        return section_map.get(str(key), {"section_type": section_type})

    def _section_type(self, chunk: dict[str, Any], metadata: dict[str, Any]) -> str:
        # Older parsers stored generic values such as `page` in `type` or
        # `chunk_type`. Keep looking until a real medical section is found.
        values = (
            chunk.get("section_type"),
            metadata.get("section_type"),
            metadata.get("type"),
            metadata.get("section"),
            chunk.get("section"),
            chunk.get("chunk_type"),
        )
        generic = {
            "",
            "page",
            "paragraph",
            "text",
            "sample",
            "section",
            "medical_section",
            "json",
            "csv",
        }
        for candidate in values:
            value = str(candidate or "").strip().lower()
            if value.startswith("medicalsectiontype."):
                value = value.split(".", 1)[1]
            value = value.replace(" ", "_").replace("-", "_")
            if value in generic:
                continue
            if "recommend" in value or value in {"recommendation", "推荐", "建议"}:
                return "recommendations"
            if "contraindicat" in value or value in {"禁忌", "禁忌证"}:
                return "contraindications"
            if value in {"figure", "figurecaption", "figure_caption"}:
                return "figure_caption"
            return value
        return "unknown"


_EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
_PROTECTED_CITATION = re.compile(
    r"(?:\bdoi\s*:\s*10\.\S+|https?://doi\.org/10\.\S+|"
    r"\b(?:pmid|pmcid|issn)\s*[:#]?\s*[A-Z0-9-]+|"
    r"\b(?:[A-Z][A-Za-z.&'-]+\s+){1,5}\d{1,4}\s*[:;]\s*"
    r"\d{1,5}\s*[-–]\s*\d{1,5}(?:\s*,\s*(?:19|20)\d{2})?)",
    re.I,
)
_PHONE = re.compile(
    r"(?ix)"
    r"(?P<label>\b(?:phone|telephone|mobile|tel|contact|电话|手机|联系方式|联系电话)\b"
    r"\s*(?:number|no\.?|号码)?\s*[:：]?\s*)?"
    r"(?P<number>\+?[0-9](?:[0-9().\-\s]{7,}[0-9])?)"
)
_IDENTIFIER = re.compile(
    r"(?im)\b(?:mrn|medical\s+record(?:\s+number)?|patient\s+id|病历号|患者编号)"
    r"\s*[:#：]?\s*[A-Z0-9][A-Z0-9-]{2,}\b"
)
_NAMED_FIELD = re.compile(
    r"(?im)^(?P<prefix>\s*(?:patient\s+name|name|患者姓名|姓名|address|地址)\s*[:：])"
    r"\s*(?P<value>.+?)\s*$"
)
_WARNING_CODE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


def _warning_codes(values: Iterable[str]) -> list[str]:
    """Keep parser warning codes while rejecting free-form source text."""
    return list(
        dict.fromkeys(
            value
            for item in values
            if isinstance(item, str)
            if (value := item.strip().lower()) and _WARNING_CODE.fullmatch(value)
        )
    )


def redact_sensitive_fields(text: str) -> tuple[str, bool]:
    """Remove direct identifiers while preserving public citation metadata.

    Journal volume/page ranges and DOI/PMID identifiers are public source
    locators, not patient contact details. Protect them before applying the
    phone rule, which is intentionally conservative but still supports
    labelled and international phone numbers.
    """
    protected: dict[str, str] = {}

    def protect(match: re.Match[str]) -> str:
        token = f"__GRAPHMIND_PUBLIC_{len(protected)}__"
        protected[token] = match.group(0)
        return token

    changed_text = _PROTECTED_CITATION.sub(protect, str(text or ""))
    changed_text = _EMAIL.sub("[REDACTED_EMAIL]", changed_text)

    def redact_phone(match: re.Match[str]) -> str:
        label = match.group("label") or ""
        number = match.group("number") or ""
        digits = re.sub(r"\D", "", number)
        # Unlabelled short numbers are overwhelmingly citation fragments,
        # sample sizes, years, or IDs. Only redact unlabelled phone-like
        # numbers when they have an international prefix or 10+ digits.
        if not label and not number.startswith("+") and len(digits) < 10:
            return match.group(0)
        return f"{label}[REDACTED_PHONE]" if label else "[REDACTED_PHONE]"

    changed_text = _PHONE.sub(redact_phone, changed_text)
    changed_text = _IDENTIFIER.sub("[REDACTED_IDENTIFIER]", changed_text)
    changed_text = _NAMED_FIELD.sub(
        lambda match: f"{match.group('prefix')} [REDACTED]",
        changed_text,
    )
    for token, original in protected.items():
        changed_text = changed_text.replace(token, original)
    return changed_text, changed_text != text


def _estimate_tokens(text: str) -> int:
    # Keep CJK characters separate. Treating a whole Chinese paragraph as one
    # word makes the context limit meaningless for papers without spaces.
    return max(1, len(_token_matches(text)))


def _truncate_text(text: str, token_budget: int) -> str:
    if token_budget <= 0:
        return ""
    matches = _token_matches(text)
    if len(matches) <= token_budget:
        return text
    if token_budget == 1:
        return "…"

    # Slice the original text so CJK punctuation and spacing stay intact.
    end = matches[token_budget - 2].end()
    candidate = text[:end].rstrip()
    return f"{candidate} …" if candidate else "…"


_TOKEN_PATTERN = re.compile(
    r"[\u3400-\u4dbf\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]"
    r"|[A-Za-z0-9_]+|[^\w\s]",
    re.UNICODE,
)


def _token_matches(text: str) -> list[re.Match[str]]:
    """Return token spans without rebuilding the source text."""
    return list(_TOKEN_PATTERN.finditer(text))


def _page_label(start: int | None, end: int | None) -> str:
    if start is None and end is None:
        return "unknown"
    if start == end or end is None:
        return str(start)
    if start is None:
        return str(end)
    return f"{start}-{end}"


def _as_int(value: Any) -> int | None:
    if value in (None, "", "unknown"):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_optional_str(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _first_present(*values: Any) -> Any:
    for value in values:
        if value is not None and value != "":
            return value
    return None
