"""Find paper sections and keep their source positions."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.services.medical.models import (
    MedicalDocumentAnalysis,
    MedicalSectionType,
    PaperStructureResult,
    StructuredSection,
)
from app.services.medical.section_normalizer import clean_heading, normalize_section_title


@dataclass(frozen=True)
class _Heading:
    start: int
    end: int
    title: str
    section_type: str
    secondary_types: tuple[str, ...]
    confidence: float


@dataclass(frozen=True)
class _PageRange:
    start: int
    end: int
    page: int


class PaperStructureParser:
    """Build section-aware chunks without inventing missing paper content."""

    REQUIRED_SECTIONS = (
        MedicalSectionType.ABSTRACT.value,
        MedicalSectionType.INTRODUCTION.value,
        MedicalSectionType.METHODS.value,
        MedicalSectionType.RESULTS.value,
        MedicalSectionType.DISCUSSION.value,
        MedicalSectionType.CONCLUSION.value,
        MedicalSectionType.LIMITATIONS.value,
        MedicalSectionType.REFERENCES.value,
    )

    _MARKDOWN_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*$")
    _PAGE_TITLE = re.compile(r"^page\s+(\d+)$", re.I)
    _HEADING_PUNCTUATION = re.compile(r"[.!?。！？]$")
    _FIGURE_CAPTION = re.compile(
        r"^(?:figure|fig\.?)\s*\d+\s*[.:：-]?\s*\S|^(?:图|図)\s*\d+\s*[.:：-]?\s*\S",
        re.I,
    )

    def __init__(self, chunk_size: int = 1200, overlap: int = 160) -> None:
        self.chunk_size = max(200, chunk_size)
        self.overlap = min(max(0, overlap), self.chunk_size // 2)

    def parse(
        self,
        parsed: dict[str, Any],
        analysis: MedicalDocumentAnalysis,
    ) -> PaperStructureResult:
        """Parse a classified research paper into traceable sections."""
        text = str(parsed.get("content") or parsed.get("raw_content") or "")
        if not text.strip():
            warning = "ocr_required" if self._format(parsed) == "pdf" else "no_extractable_text"
            return PaperStructureResult(warnings=[warning], missing_sections=list(self.REQUIRED_SECTIONS))

        explicit = self._docx_sections(parsed)
        if explicit:
            sections = self._sections_from_explicit_blocks(explicit, text, analysis.language)
        else:
            sections = self._sections_from_headings(parsed, text, analysis.language)

        if not sections:
            sections = [
                self._section(
                    section_type=MedicalSectionType.UNKNOWN.value,
                    title="",
                    start=0,
                    end=len(text),
                    text=text.strip(),
                    language=analysis.language,
                    confidence=0.2,
                    pages=self._page_ranges(parsed, text),
                    heading_detected=False,
                )
            ]

        table_sections, _ = self._table_parts(
            parsed, text, analysis.language, analysis.document_kind
        )
        figure_sections = self._figure_parts(
            parsed, text, analysis.language, analysis.document_kind
        )
        sections.extend([*table_sections, *figure_sections])
        sections.sort(key=lambda item: (item.char_start, item.ordinal))
        self._renumber(sections)

        # Number sections first so the same number is stored on each chunk.
        chunks: list[dict[str, Any]] = []
        for section in sections:
            section_chunks = self._section_chunks(section, analysis.document_kind)
            section.chunk_count = len(section_chunks)
            chunks.extend(section_chunks)
        for chunk_index, chunk in enumerate(chunks):
            chunk["chunk_index"] = chunk_index

        present = {
            section.section_type
            for section in sections
            if section.section_type != MedicalSectionType.UNKNOWN.value
        }
        present.update(
            secondary
            for section in sections
            for secondary in section.secondary_types
        )
        missing = [section for section in self.REQUIRED_SECTIONS if section not in present]
        warnings = []
        if self._format(parsed) == "pdf" and not self._page_ranges(parsed, text):
            warnings.append("page_location_unavailable")
        if any(
            not section.metadata.get("location_exact", True)
            for section in table_sections
        ):
            warnings.append("table_location_unavailable")
        if any(
            not section.metadata.get("location_exact", True)
            for section in figure_sections
        ):
            warnings.append("figure_location_unavailable")
        return PaperStructureResult(
            sections=sections,
            chunks=chunks,
            missing_sections=missing,
            warnings=warnings,
        )

    def _sections_from_headings(
        self,
        parsed: dict[str, Any],
        text: str,
        language: str,
    ) -> list[StructuredSection]:
        headings = self._find_headings(parsed, text)
        pages = self._page_ranges(parsed, text)
        sections: list[StructuredSection] = []

        if headings and headings[0].start > 0:
            prefix = text[:headings[0].start].strip()
            if prefix:
                prefix_start = len(text[:headings[0].start]) - len(text[:headings[0].start].lstrip())
                sections.append(
                    self._section(
                        MedicalSectionType.TITLE.value,
                        "Document title and front matter",
                        prefix_start,
                        headings[0].start,
                        prefix,
                        language,
                        0.55,
                        pages,
                        False,
                    )
                )

        for index, heading in enumerate(headings):
            content_start = heading.end
            content_end = headings[index + 1].start if index + 1 < len(headings) else len(text)
            content_start, content_end, section_text = self._trim_range(
                text, content_start, content_end
            )
            sections.append(
                self._section(
                    heading.section_type,
                    heading.title,
                    content_start,
                    content_end,
                    section_text,
                    language,
                    heading.confidence,
                    pages,
                    True,
                    list(heading.secondary_types),
                )
            )
        return sections

    def _sections_from_explicit_blocks(
        self,
        blocks: list[dict[str, Any]],
        text: str,
        language: str,
    ) -> list[StructuredSection]:
        """DOCX keeps heading titles outside the raw text; use its blocks."""
        sections: list[StructuredSection] = []
        cursor = 0
        for block in blocks:
            title = str(block.get("title") or block.get("header") or "").strip()
            content = str(block.get("content") or "").strip()
            if not title and not content:
                continue
            if content:
                found = text.find(content, cursor)
                if found < 0:
                    found = text.find(content)
                start = found if found >= 0 else cursor
                end = start + len(content)
                cursor = min(len(text), end)
                location_exact = found >= 0
            else:
                start = cursor
                end = cursor
                location_exact = False
            normalized = normalize_section_title(title)
            sections.append(
                self._section(
                    normalized.primary,
                    title,
                    start,
                    end,
                    content,
                    language,
                    normalized.confidence if title else 0.2,
                    [],
                    bool(title),
                    normalized.secondary,
                    location_exact=location_exact,
                )
            )
        return sections

    def _find_headings(self, parsed: dict[str, Any], text: str) -> list[_Heading]:
        offsets = self._line_offsets(text)
        candidates: list[_Heading] = []

        # Markdown headings are unambiguous, including headings we do not know.
        for line_number, line in enumerate(text.splitlines(keepends=True)):
            match = self._MARKDOWN_HEADING.match(line.rstrip("\r\n"))
            if not match:
                continue
            title = clean_heading(match.group(1))
            normalized = normalize_section_title(title)
            start = offsets[line_number]
            end = offsets[line_number] + len(line)
            candidates.append(
                _Heading(
                    start,
                    end,
                    title,
                    normalized.primary,
                    tuple(normalized.secondary),
                    normalized.confidence,
                )
            )

        # PDF text extraction often leaves headings as standalone lines.
        for line_number, line in enumerate(text.splitlines(keepends=True)):
            title = line.strip()
            if not title or len(title) > 120 or self._HEADING_PUNCTUATION.search(title):
                continue
            normalized = normalize_section_title(title)
            if normalized.primary == MedicalSectionType.UNKNOWN.value:
                continue
            start = offsets[line_number] + len(line) - len(line.lstrip())
            end = offsets[line_number] + len(line.rstrip("\r\n"))
            candidates.append(
                _Heading(
                    start,
                    end,
                    clean_heading(title),
                    normalized.primary,
                    tuple(normalized.secondary),
                    normalized.confidence,
                )
            )

        # Layout hints are useful when a PDF heading was not on its own line.
        for item in (parsed.get("metadata") or {}).get("headings", []):
            if not isinstance(item, dict) or not item.get("text"):
                continue
            title = clean_heading(str(item["text"]))
            normalized = normalize_section_title(title)
            if normalized.primary == MedicalSectionType.UNKNOWN.value:
                continue
            page = int(item.get("page", 0) or 0)
            start = self._find_on_page(text, title, parsed, page)
            if start is not None:
                candidates.append(
                    _Heading(
                        start,
                        start + len(title),
                        title,
                        normalized.primary,
                        tuple(normalized.secondary),
                        min(normalized.confidence, 0.8),
                    )
                )

        candidates.sort(key=lambda item: (item.start, item.end))
        result: list[_Heading] = []
        seen: set[tuple[int, str]] = set()
        for candidate in candidates:
            key = (candidate.start, candidate.title.casefold())
            if key in seen:
                continue
            seen.add(key)
            if result and candidate.start < result[-1].end:
                continue
            result.append(candidate)
        return result

    def _docx_sections(self, parsed: dict[str, Any]) -> list[dict[str, Any]]:
        if self._format(parsed) != "docx":
            return []
        sections = (parsed.get("extra") or {}).get("sections", [])
        return [item for item in sections if isinstance(item, dict)]

    def _page_ranges(self, parsed: dict[str, Any], text: str) -> list[_PageRange]:
        ranges: list[_PageRange] = []
        cursor = 0
        extra_sections = (parsed.get("extra") or {}).get("sections", [])
        for item in extra_sections:
            if not isinstance(item, dict):
                continue
            match = self._PAGE_TITLE.match(str(item.get("title") or "").strip())
            content = str(item.get("content") or "").strip()
            if not match or not content:
                continue
            start = text.find(content, cursor)
            if start < 0:
                start = text.find(content)
            if start < 0:
                continue
            end = start + len(content)
            ranges.append(_PageRange(start, end, int(match.group(1))))
            cursor = end

        if ranges:
            return ranges

        # This also works with parser output that only kept page on chunks.
        by_page: dict[int, list[str]] = {}
        for chunk in parsed.get("chunks", []):
            if not isinstance(chunk, dict) or not chunk.get("page"):
                continue
            page = int(chunk["page"])
            value = str(chunk.get("text") or "").strip()
            if value:
                by_page.setdefault(page, []).append(value)
        cursor = 0
        for page in sorted(by_page):
            needle = by_page[page][0]
            start = text.find(needle, cursor)
            if start < 0:
                continue
            end = start + len("\n".join(by_page[page]))
            ranges.append(_PageRange(start, min(len(text), end), page))
            cursor = end
        return ranges

    def _find_on_page(
        self,
        text: str,
        title: str,
        parsed: dict[str, Any],
        page: int,
    ) -> int | None:
        ranges = [item for item in self._page_ranges(parsed, text) if item.page == page]
        for page_range in ranges:
            found = text.find(title, page_range.start, page_range.end)
            if found >= 0:
                return found
        found = text.find(title)
        return found if found >= 0 else None

    def _section(
        self,
        section_type: str,
        title: str,
        start: int,
        end: int,
        text: str,
        language: str,
        confidence: float,
        pages: list[_PageRange],
        heading_detected: bool,
        secondary_types: list[str] | None = None,
        location_exact: bool = True,
    ) -> StructuredSection:
        page_start, page_end = self._pages_for_range(start, end, pages)
        return StructuredSection(
            section_type=section_type,
            original_title=title,
            ordinal=0,
            page_start=page_start,
            page_end=page_end,
            char_start=start,
            char_end=end,
            text=text,
            language=language,
            confidence=confidence,
            secondary_types=secondary_types or [],
            metadata={
                "evidence_role": self._evidence_role(section_type),
                "heading_detected": heading_detected,
                "location_exact": location_exact,
            },
        )

    def _section_chunks(self, section: StructuredSection, document_kind: str) -> list[dict[str, Any]]:
        if not section.text.strip():
            return []
        chunks: list[dict[str, Any]] = []
        start = 0
        text = section.text
        while start < len(text):
            end = min(len(text), start + self.chunk_size)
            raw_piece = text[start:end]
            piece = raw_piece.strip()
            if piece:
                location_exact = bool(section.metadata.get("location_exact", True))
                if location_exact:
                    leading = len(raw_piece) - len(raw_piece.lstrip())
                    trailing = len(raw_piece) - len(raw_piece.rstrip())
                    absolute_start = section.char_start + start + leading
                    absolute_end = section.char_start + end - trailing
                else:
                    absolute_start = 0
                    absolute_end = 0
                chunks.append({
                    "text": piece,
                    "type": "medical_section",
                    "start": absolute_start,
                    "end": absolute_end,
                    "char_start": absolute_start,
                    "char_end": absolute_end,
                    "section_type": section.section_type,
                    "section_title": section.original_title,
                    "section_ordinal": section.ordinal,
                    "page_start": section.page_start,
                    "page_end": section.page_end,
                    "language": section.language,
                    "document_kind": document_kind,
                    "evidence_role": section.metadata.get("evidence_role", "context"),
                    "location_exact": location_exact,
                })
            if end >= len(text):
                break
            start = max(start + 1, end - self.overlap)
        return chunks

    def _table_parts(
        self,
        parsed: dict[str, Any],
        text: str,
        language: str,
        document_kind: str,
    ) -> tuple[list[StructuredSection], list[dict[str, Any]]]:
        sections: list[StructuredSection] = []
        chunks: list[dict[str, Any]] = []
        tables = (parsed.get("extra") or {}).get("tables", [])
        for index, table in enumerate(tables, 1):
            if not isinstance(table, dict):
                continue
            headers = [str(value or "").strip() for value in table.get("headers", [])]
            rows = table.get("rows", [])
            table_text = " | ".join(headers)
            if rows:
                table_text += "\n" + "\n".join(
                    " | ".join(str(value or "").strip() for value in row)
                    for row in rows[:20]
                    if isinstance(row, list)
                )
            table_text = table_text.strip()
            if not table_text:
                continue
            caption = str(table.get("caption") or f"Table {index}")
            page = self._caption_page(caption)
            start = text.find(table_text)
            end = start + len(table_text) if start >= 0 else 0
            section = StructuredSection(
                section_type=MedicalSectionType.TABLE.value,
                original_title=caption,
                ordinal=0,
                page_start=page,
                page_end=page,
                char_start=start if start >= 0 else 0,
                char_end=end,
                text=table_text,
                language=language,
                confidence=0.9,
                metadata={
                    "evidence_role": "table",
                    "heading_detected": False,
                    "location_exact": start >= 0,
                },
            )
            section_chunks = self._section_chunks(section, document_kind)
            section.chunk_count = len(section_chunks)
            sections.append(section)
            chunks.extend(section_chunks)
        return sections, chunks

    def _figure_parts(
        self,
        parsed: dict[str, Any],
        text: str,
        language: str,
        document_kind: str,
    ) -> list[StructuredSection]:
        """Keep simple figure captions as separate, searchable evidence."""
        pages = self._page_ranges(parsed, text)
        sections: list[StructuredSection] = []
        cursor = 0
        for line in text.splitlines(keepends=True):
            caption = line.strip()
            line_start = cursor
            cursor += len(line)
            if not caption or not self._FIGURE_CAPTION.search(caption):
                continue

            start = line_start + len(line) - len(line.lstrip())
            end = start + len(caption)
            page_start, page_end = self._pages_for_range(start, end, pages)
            section = StructuredSection(
                section_type=MedicalSectionType.FIGURE_CAPTION.value,
                original_title=caption,
                ordinal=0,
                page_start=page_start,
                page_end=page_end,
                char_start=start,
                char_end=end,
                text=caption,
                language=language,
                confidence=0.9,
                metadata={
                    "evidence_role": "figure_caption",
                    "heading_detected": False,
                    "location_exact": True,
                },
            )
            section.chunk_count = len(
                self._section_chunks(section, document_kind)
            )
            sections.append(section)
        return sections

    def _trim_range(self, text: str, start: int, end: int) -> tuple[int, int, str]:
        value = text[start:end]
        stripped = value.strip()
        if not stripped:
            return end, end, ""
        leading = len(value) - len(value.lstrip())
        trailing = len(value) - len(value.rstrip())
        left = start + leading
        right = end - trailing
        return left, right, stripped

    def _line_offsets(self, text: str) -> list[int]:
        offsets = []
        cursor = 0
        for line in text.splitlines(keepends=True):
            offsets.append(cursor)
            cursor += len(line)
        if not offsets or cursor < len(text):
            offsets.append(cursor)
        return offsets

    def _pages_for_range(self, start: int, end: int, pages: list[_PageRange]) -> tuple[int | None, int | None]:
        if not pages:
            return None, None
        last = max(start, end - 1)
        matches = [item for item in pages if item.start <= last and item.end >= start]
        if not matches:
            before = [item for item in pages if item.start <= start]
            if before:
                return before[-1].page, before[-1].page
            return pages[0].page, pages[0].page
        return matches[0].page, matches[-1].page

    def _caption_page(self, caption: str) -> int | None:
        match = re.search(r"(?:page\s+|p\.?\s*)(\d+)", caption, re.I)
        return int(match.group(1)) if match else None

    def _format(self, parsed: dict[str, Any]) -> str:
        return str((parsed.get("metadata") or {}).get("format") or "").lower()

    def _renumber(self, sections: list[StructuredSection]) -> None:
        for ordinal, section in enumerate(sections, 1):
            section.ordinal = ordinal

    def _evidence_role(self, section_type: str) -> str:
        return {
            "title": "study_title",
            "abstract": "study_summary",
            "introduction": "background",
            "methods": "study_method",
            "population": "study_population",
            "intervention": "study_intervention",
            "comparator": "study_comparator",
            "outcomes": "study_outcome",
            "results": "study_result",
            "adverse_events": "safety",
            "discussion": "interpretation",
            "conclusion": "author_conclusion",
            "limitations": "study_limitation",
            "references": "reference",
            "supplementary": "supplementary_material",
            "table": "table",
            "figure_caption": "figure_caption",
        }.get(section_type, "context")
