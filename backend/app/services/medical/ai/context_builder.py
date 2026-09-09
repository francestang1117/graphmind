"""Select source chunks for one analysis and attach stable evidence ids."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable


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


@dataclass
class AnalysisContext:
    title: str
    document_kind: str
    language: str
    evidence: list[EvidenceItem] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    total_chunks: int = 0
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

        safe_title = title or "Untitled medical document"
        title_redacted = False
        if redact_pii:
            safe_title, title_redacted = redact_sensitive_fields(safe_title)

        for index, raw_chunk in enumerate(chunks):
            if not isinstance(raw_chunk, dict):
                continue
            text = str(raw_chunk.get("text") or "").strip()
            if not text:
                continue
            metadata = raw_chunk.get("metadata")
            metadata = metadata if isinstance(metadata, dict) else {}
            section_type = self._section_type(raw_chunk, metadata)
            section = self._section_for(raw_chunk, metadata, section_type, section_map)
            if section_type == "unknown":
                # Some older rows only keep the section id. The section row
                # still has enough information to restore its label here.
                section_type = self._section_type(
                    section,
                    section.get("metadata") if isinstance(section.get("metadata"), dict) else {},
                )
            chunk_id = str(raw_chunk.get("id") or f"chunk:{index}")
            dedupe_key = (chunk_id, text)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            normalized = {
                "raw": raw_chunk,
                "metadata": metadata,
                "text": text,
                "section_type": section_type,
                "section": section,
                "index": index,
            }
            candidates.append((self.PRIORITY.get(section_type, 10), index, normalized))

        candidates.sort(key=lambda value: (value[0], value[1]))
        budget = max(1, int(max_input_tokens or 1))
        selected: list[EvidenceItem] = []
        selected_indexes: set[int] = set()
        warnings = _warning_codes(source_warnings or [])
        redacted = title_redacted
        truncated = False
        skipped = False
        remaining = budget

        def add_candidate(candidate: dict[str, Any], allowance: int) -> None:
            nonlocal redacted, remaining, truncated, skipped
            index = candidate["index"]
            if index in selected_indexes:
                return
            if remaining <= 0:
                skipped = True
                return
            allowed = max(1, min(remaining, allowance))
            source_text = candidate["text"]
            source_tokens = _estimate_tokens(source_text)
            item_truncated = source_tokens > allowed
            text = _truncate_text(source_text, allowed) if item_truncated else source_text
            if not text:
                skipped = True
                return
            token_count = _estimate_tokens(text)
            truncated = truncated or item_truncated

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
                    token_count=token_count,
                    source_index=index,
                    truncated=item_truncated,
                )
            )
            selected_indexes.add(index)
            remaining = max(0, remaining - token_count)

        # Give each non-reference section a share before spending the rest on
        # high-priority findings. This prevents a long Results section from
        # crowding Methods, population, and limitations out of the analysis.
        first_by_section: dict[str, dict[str, Any]] = {}
        for _priority, _index, candidate in candidates:
            section_type = candidate["section_type"]
            if section_type in {"references", "reference", "bibliography"}:
                continue
            first_by_section.setdefault(section_type, candidate)
        section_candidates = list(first_by_section.values())
        for position, candidate in enumerate(section_candidates):
            sections_left = len(section_candidates) - position
            add_candidate(candidate, max(1, remaining // max(1, sections_left)))

        for _priority, _index, candidate in candidates:
            if remaining <= 0:
                skipped = skipped or candidate["index"] not in selected_indexes
                continue
            add_candidate(candidate, remaining)

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
            )
            for index, item in enumerate(selected, start=1)
        ]

        if redacted:
            warnings.append("pii_redacted")
        if truncated or skipped or len(selected) < len(candidates):
            warnings.append("context_truncated")
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
            total_tokens=sum(_estimate_tokens(candidate[2]["text"]) for candidate in candidates),
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
_PHONE = re.compile(r"(?<!\w)\+?[0-9][0-9().\-\s]{7,}[0-9](?!\w)")
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
    """Remove common contact and record identifiers before an external call."""
    changed_text = _EMAIL.sub("[REDACTED_EMAIL]", text)
    changed_text = _PHONE.sub("[REDACTED_PHONE]", changed_text)
    changed_text = _IDENTIFIER.sub("[REDACTED_IDENTIFIER]", changed_text)
    changed_text = _NAMED_FIELD.sub(
        lambda match: f"{match.group('prefix')} [REDACTED]",
        changed_text,
    )
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
