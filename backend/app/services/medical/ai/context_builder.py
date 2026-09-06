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
        "limitations": 1,
        "adverse_events": 1,
        "conclusion": 2,
        "abstract": 3,
        "population": 4,
        "intervention": 4,
        "comparator": 4,
        "outcomes": 4,
        "methods": 5,
        "discussion": 6,
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
        title: str = "",
        document_kind: str = "unknown",
        language: str = "unknown",
        max_input_tokens: int = 12000,
        redact_pii: bool = True,
    ) -> AnalysisContext:
        section_map = self._section_map(sections or [])
        candidates: list[tuple[int, int, dict[str, Any]]] = []
        seen: set[tuple[str, str]] = set()

        for index, raw_chunk in enumerate(chunks):
            if not isinstance(raw_chunk, dict):
                continue
            text = str(raw_chunk.get("text") or "").strip()
            if not text:
                continue
            metadata = raw_chunk.get("metadata")
            metadata = metadata if isinstance(metadata, dict) else {}
            section_type = self._section_type(raw_chunk, metadata)
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
                "section": self._section_for(raw_chunk, metadata, section_type, section_map),
                "index": index,
            }
            candidates.append((self.PRIORITY.get(section_type, 10), index, normalized))

        candidates.sort(key=lambda value: (value[0], value[1]))
        budget = max(1, int(max_input_tokens or 1))
        selected: list[EvidenceItem] = []
        warnings: list[str] = []
        redacted = False
        truncated = False
        skipped = False
        remaining = budget

        for _priority, _index, candidate in candidates:
            token_count = _estimate_tokens(candidate["text"])
            if remaining <= 0:
                skipped = True
                continue
            item_truncated = False
            if token_count > remaining:
                text = _truncate_text(candidate["text"], remaining)
                if not text:
                    skipped = True
                    continue
                truncated = True
                item_truncated = True
                token_count = _estimate_tokens(text)
            else:
                text = candidate["text"]

            if redact_pii:
                text, changed = redact_sensitive_fields(text)
                redacted = redacted or changed

            raw = candidate["raw"]
            metadata = candidate["metadata"]
            section = candidate["section"]
            selected.append(
                EvidenceItem(
                    evidence_id=f"EVIDENCE_{len(selected) + 1:03d}",
                    chunk_id=str(raw.get("id") or f"chunk:{candidate['index']}"),
                    section_id=_as_optional_str(
                        raw.get("section_id") or metadata.get("section_id") or section.get("id")
                    ),
                    section_type=candidate["section_type"],
                    section_title=str(
                        raw.get("section_title")
                        or metadata.get("section_title")
                        or metadata.get("section")
                        or section.get("original_title")
                        or ""
                    ),
                    page_start=_as_int(
                        raw.get("page_start")
                        if raw.get("page_start") is not None
                        else metadata.get("page_start")
                        if metadata.get("page_start") is not None
                        else section.get("page_start")
                    ),
                    page_end=_as_int(
                        raw.get("page_end")
                        if raw.get("page_end") is not None
                        else metadata.get("page_end")
                        if metadata.get("page_end") is not None
                        else section.get("page_end")
                    ),
                    character_start=_as_int(
                        raw.get("char_start")
                        if raw.get("char_start") is not None
                        else metadata.get("char_start")
                    ),
                    character_end=_as_int(
                        raw.get("char_end")
                        if raw.get("char_end") is not None
                        else metadata.get("char_end")
                    ),
                    text=text,
                    token_count=token_count,
                    source_index=candidate["index"],
                    truncated=item_truncated,
                )
            )
            remaining = max(0, remaining - token_count)

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
        return AnalysisContext(
            title=title or "Untitled medical document",
            document_kind=document_kind or "unknown",
            language=language or "unknown",
            evidence=selected,
            warnings=warnings,
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
        value = (
            chunk.get("section_type")
            or metadata.get("section_type")
            or metadata.get("section")
            or chunk.get("section")
            or "unknown"
        )
        value = str(value).strip().lower()
        if value.startswith("medicalsectiontype."):
            value = value.split(".", 1)[1]
        value = value.replace(" ", "_").replace("-", "_")
        if "recommend" in value:
            return "recommendations"
        if value in {"figure", "figurecaption", "figure_caption"}:
            return "figure_caption"
        return value or "unknown"


_EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
_PHONE = re.compile(r"(?<!\w)\+?[0-9][0-9().\-\s]{7,}[0-9](?!\w)")
_IDENTIFIER = re.compile(
    r"(?im)\b(?:mrn|medical\s+record(?:\s+number)?|patient\s+id|病历号|患者编号)"
    r"\s*[:#：]?\s*[A-Z0-9][A-Z0-9-]{2,}\b"
)
_NAMED_FIELD = re.compile(
    r"(?im)^\s*(?:patient\s+name|name|患者姓名|姓名|address|地址)\s*[:：].*$"
)


def redact_sensitive_fields(text: str) -> tuple[str, bool]:
    """Remove common contact and record identifiers before an external call."""
    changed_text = _EMAIL.sub("[REDACTED_EMAIL]", text)
    changed_text = _PHONE.sub("[REDACTED_PHONE]", changed_text)
    changed_text = _IDENTIFIER.sub("[REDACTED_IDENTIFIER]", changed_text)
    changed_text = _NAMED_FIELD.sub(lambda match: match.group(0).split(":", 1)[0] + ": [REDACTED]", changed_text)
    return changed_text, changed_text != text


def _estimate_tokens(text: str) -> int:
    # A rough count keeps the provider independent of tokenizer packages.
    return max(1, len(re.findall(r"\w+|[^\w\s]", text, re.UNICODE)))


def _truncate_text(text: str, token_budget: int) -> str:
    if token_budget <= 0:
        return ""
    tokens = re.findall(r"\w+|[^\w\s]", text, re.UNICODE)
    if len(tokens) <= token_budget:
        return text
    # Word boundaries are preferable for English; the token fallback still
    # keeps Chinese text usable when there are no spaces.
    candidate = " ".join(tokens[:token_budget]).strip()
    return f"{candidate} …" if candidate else ""


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
