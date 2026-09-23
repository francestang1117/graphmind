"""Find paper sections and keep their source positions."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
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
    source: str = "text"


@dataclass(frozen=True)
class _PageRange:
    start: int
    end: int
    page: int


class PaperStructureParser:
    """Build page-aware chunks for papers and clinical guidelines."""

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
    GUIDELINE_SECTIONS = (
        MedicalSectionType.SCOPE.value,
        MedicalSectionType.RECOMMENDATIONS.value,
        MedicalSectionType.POPULATION.value,
        MedicalSectionType.EVIDENCE.value,
        MedicalSectionType.CONTRAINDICATIONS.value,
    )

    _MARKDOWN_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*$")
    _PAGE_TITLE = re.compile(r"^page\s+(\d+)$", re.I)
    _HEADING_PUNCTUATION = re.compile(r"[.!?。！？]$")
    _FIGURE_CAPTION = re.compile(
        r"^(?:figure|fig\.?)\s*\d+\s*[.:：-]?\s*\S|^(?:图|図)\s*\d+\s*[.:：-]?\s*\S",
        re.I,
    )
    _STRUCTURED_ABSTRACT_LABEL = re.compile(
        r"(?<![A-Za-z])(?P<label>Objectives?|Methods?|Results?|"
        r"Conclusion|Conclusions|目的|方法|结果|結論|结论)"
        r"(?=\s+|[:：])",
        re.I,
    )
    _SENTENCE_END = re.compile(r"[.!?。！？](?=\s|$)|\n{2,}")
    _REFERENCE_LINE = re.compile(
        r"^\s*(?:\[?\d{1,3}\]?\s*[.)]|"
        r"(?:doi\s*:\s*10\.|https?://doi\.org/10\.)|"
        r"[A-Z][^\n]{3,100}\b(?:19|20)\d{2}\b[^\n]{0,80}"
        r"\b\d{1,4}\s*[:;]\s*\d{1,5})",
        re.I,
    )
    _REFERENCE_AUTHOR_LINE = re.compile(
        r"\b(?:et\s+al\.?|[A-Z][a-z]+\s+[A-Z](?:\.|\b))\b.*\b(?:19|20)\d{2}\b",
        re.I,
    )
    _NON_MEDICAL_TYPES = frozenset(
        {
            "references",
            "supplementary",
            "acknowledgements",
            "acknowledgments",
            "funding",
            "author_contributions",
            "conflicts_of_interest",
        }
    )

    def __init__(self, chunk_size: int = 1200, overlap: int = 160) -> None:
        self.chunk_size = max(200, chunk_size)
        self.overlap = min(max(0, overlap), self.chunk_size // 2)

    def parse(
        self,
        parsed: dict[str, Any],
        analysis: MedicalDocumentAnalysis,
    ) -> PaperStructureResult:
        """Parse a classified paper or guideline into traceable sections."""
        required_sections = self._required_sections(analysis.document_kind)
        text = str(parsed.get("content") or parsed.get("raw_content") or "")
        extraction_warnings = self._pdf_extraction_warnings(parsed)
        if not text.strip():
            warning = "ocr_required" if self._format(parsed) == "pdf" else "no_extractable_text"
            return PaperStructureResult(
                warnings=[*extraction_warnings, warning],
                missing_sections=list(required_sections),
            )

        pages = self._page_ranges(parsed, text)
        pdf_blocks = self._pdf_blocks(parsed)
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

        sections = self._expand_structured_abstracts(
            sections,
            text,
            analysis.language,
            pages,
        )

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
            section_chunks = self._section_chunks(
                section, analysis.document_kind, pages, pdf_blocks
            )
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
        missing = [section for section in required_sections if section not in present]
        warnings = [*extraction_warnings]
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

    def _pdf_extraction_warnings(self, parsed: dict[str, Any]) -> list[str]:
        """Expose parser quality to the analysis task without copying source text."""
        if self._format(parsed) != "pdf":
            return []
        metadata = parsed.get("metadata")
        if not isinstance(metadata, dict):
            return []
        quality = str(metadata.get("text_quality") or "").strip().lower()
        warnings: list[str] = []
        if quality == "unreadable":
            warnings.append("pdf_text_unreadable")
        elif quality == "degraded":
            warnings.append("pdf_text_degraded")
        for warning in metadata.get("extraction_warnings") or []:
            if warning == "pdf_text_reconstructed":
                warnings.append(warning)
        return list(dict.fromkeys(warnings))

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
            content_end = self._non_medical_tail_start(
                text,
                content_start,
                content_end,
                heading.section_type,
            )
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

    def _non_medical_tail_start(
        self,
        text: str,
        start: int,
        end: int,
        section_type: str,
    ) -> int:
        """Stop medical sections before acknowledgements and bibliography tails."""
        if section_type in self._NON_MEDICAL_TYPES:
            return end
        value = text[start:end]
        cursor = 0
        lines = value.splitlines(keepends=True)
        for line in lines:
            title = clean_heading(line.strip())
            normalized = normalize_section_title(title)
            if normalized.primary in self._NON_MEDICAL_TYPES:
                return start + cursor
            cursor += len(line)

        # When a PDF loses the References heading, require two independent
        # bibliography-shaped lines before cutting anything. One in-text
        # citation must never erase the end of a conclusion or result.
        candidates: list[int] = []
        offsets: list[int] = []
        cursor = 0
        for line in lines:
            stripped = line.strip()
            if stripped and (
                self._REFERENCE_LINE.search(stripped)
                or self._REFERENCE_AUTHOR_LINE.search(stripped)
            ):
                candidates.append(len(offsets))
            offsets.append(cursor)
            cursor += len(line)
        for index in candidates:
            nearby = [candidate for candidate in candidates if index <= candidate <= index + 8]
            if len(nearby) >= 2 and index > 0:
                return start + offsets[index]
        return end

    def _expand_structured_abstracts(
        self,
        sections: list[StructuredSection],
        text: str,
        language: str,
        pages: list[_PageRange],
    ) -> list[StructuredSection]:
        """Split inline abstract labels before providers assign semantic roles."""
        expanded: list[StructuredSection] = []
        type_by_label = {
            "objective": MedicalSectionType.SCOPE.value,
            "objectives": MedicalSectionType.SCOPE.value,
            "method": MedicalSectionType.METHODS.value,
            "methods": MedicalSectionType.METHODS.value,
            "result": MedicalSectionType.RESULTS.value,
            "results": MedicalSectionType.RESULTS.value,
            "conclusion": MedicalSectionType.CONCLUSION.value,
            "conclusions": MedicalSectionType.CONCLUSION.value,
            "目的": MedicalSectionType.SCOPE.value,
            "方法": MedicalSectionType.METHODS.value,
            "结果": MedicalSectionType.RESULTS.value,
            "結論": MedicalSectionType.CONCLUSION.value,
            "结论": MedicalSectionType.CONCLUSION.value,
        }

        for section in sections:
            if section.section_type != MedicalSectionType.ABSTRACT.value:
                expanded.append(section)
                continue

            matches = [
                match
                for match in self._STRUCTURED_ABSTRACT_LABEL.finditer(section.text)
                if not match.group("label").isascii()
                or match.group("label")[:1].isupper()
            ]
            if len(matches) < 2:
                expanded.append(section)
                continue

            parent_metadata = dict(section.metadata)
            parent_metadata["structured_abstract_parent"] = True
            expanded.append(replace(section, metadata=parent_metadata))
            for index, match in enumerate(matches):
                label = match.group("label")
                section_type = type_by_label.get(label.casefold())
                if section_type is None:
                    continue
                relative_end = (
                    matches[index + 1].start()
                    if index + 1 < len(matches)
                    else len(section.text)
                )
                content_start = match.end()
                while content_start < relative_end and section.text[content_start] in " \t\r\n:：":
                    content_start += 1
                start, end, section_text = self._trim_range(
                    text,
                    section.char_start + content_start,
                    section.char_start + relative_end,
                )
                if not section_text:
                    continue
                child = self._section(
                    section_type,
                    label,
                    start,
                    end,
                    section_text,
                    language,
                    max(0.0, section.confidence - 0.02),
                    pages,
                    False,
                    location_exact=bool(section.metadata.get("location_exact", True)),
                )
                child.metadata["structured_abstract_label"] = True
                expanded.append(child)
        return expanded

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
                    source="markdown",
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
                    source="text",
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
                        source="layout",
                    )
                )

        source_priority = {"markdown": 3, "text": 2, "layout": 1}
        candidates.sort(
            key=lambda item: (
                item.start,
                -(item.end - item.start),
                -item.confidence,
                -source_priority.get(item.source, 0),
            )
        )
        result: list[_Heading] = []
        seen: set[tuple[int, str]] = set()
        for candidate in candidates:
            key = (candidate.start, candidate.title.casefold())
            if key in seen:
                continue
            seen.add(key)
            # A PDF layout hint may be one word from a compound heading.
            # Keep the complete heading when it covers the same text range.
            if candidate.source == "layout" and any(
                accepted.start <= candidate.start
                and candidate.end <= accepted.end
                and accepted.source != "layout"
                for accepted in result
            ):
                continue
            if result and candidate.start < result[-1].end:
                continue
            result.append(candidate)
        return result

    def _docx_sections(self, parsed: dict[str, Any]) -> list[dict[str, Any]]:
        if self._format(parsed) != "docx":
            return []
        sections = (parsed.get("extra") or {}).get("sections", [])
        return [
            item
            for item in sections
            if isinstance(item, dict) and self._is_styled_docx_heading(item)
        ]

    def _is_styled_docx_heading(self, block: dict[str, Any]) -> bool:
        """Only a real Word heading style should bypass text heading detection."""
        title = str(block.get("title") or block.get("header") or "").strip()
        if not title or self._PAGE_TITLE.match(title):
            return False
        try:
            level = int(block.get("level", 0) or 0)
        except (TypeError, ValueError):
            return False
        return level > 0

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

    def _section_chunks(
        self,
        section: StructuredSection,
        document_kind: str,
        pages: list[_PageRange] | None = None,
        pdf_blocks: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        if not section.text.strip() or section.metadata.get("structured_abstract_parent"):
            return []
        chunks: list[dict[str, Any]] = []
        text = section.text
        spans = self._sentence_spans(text)
        location_exact = bool(section.metadata.get("location_exact", True))
        start_index = 0
        while start_index < len(spans):
            chunk_start = spans[start_index][0]
            chunk_end = spans[start_index][1]
            end_index = start_index + 1
            while (
                end_index < len(spans)
                and spans[end_index][1] - chunk_start <= self.chunk_size
            ):
                if location_exact:
                    candidate_start = section.char_start + chunk_start
                    candidate_end = section.char_start + spans[end_index][1]
                    if self._pdf_chunk_metadata(
                        candidate_start,
                        candidate_end,
                        pdf_blocks or [],
                        location_exact=True,
                    ).get("reject"):
                        break
                chunk_end = spans[end_index][1]
                end_index += 1

            piece = text[chunk_start:chunk_end]
            if piece:
                if location_exact:
                    absolute_start = section.char_start + chunk_start
                    absolute_end = section.char_start + chunk_end
                else:
                    absolute_start = 0
                    absolute_end = 0
                chunk_page_start = section.page_start
                chunk_page_end = section.page_end
                if location_exact and pages and absolute_end > absolute_start:
                    located_start, located_end = self._pages_for_range(
                        absolute_start, absolute_end, pages
                    )
                    if located_start is not None:
                        chunk_page_start = located_start
                        chunk_page_end = located_end
                block_metadata = self._pdf_chunk_metadata(
                    absolute_start,
                    absolute_end,
                    pdf_blocks or [],
                    location_exact=location_exact,
                )
                if block_metadata.get("reject"):
                    start_index = end_index
                    continue
                chunk = {
                    "text": piece,
                    "type": "medical_section",
                    "start": absolute_start,
                    "end": absolute_end,
                    "char_start": absolute_start,
                    "char_end": absolute_end,
                    "section_type": section.section_type,
                    "section_title": section.original_title,
                    "section_ordinal": section.ordinal,
                    "page_start": chunk_page_start,
                    "page_end": chunk_page_end,
                    "section_page_start": section.page_start,
                    "section_page_end": section.page_end,
                    "language": section.language,
                    "document_kind": document_kind,
                    "evidence_role": section.metadata.get("evidence_role", "context"),
                    "location_exact": location_exact,
                    "starts_at_sentence_boundary": True,
                    "ends_at_sentence_boundary": True,
                }
                chunk.update(
                    {
                        key: value
                        for key, value in block_metadata.items()
                        if key != "reject"
                    }
                )
                chunks.append(chunk)
            if end_index >= len(spans):
                break
            target = chunk_end - self.overlap
            next_index = end_index
            for candidate_index in range(end_index - 1, start_index, -1):
                if spans[candidate_index][0] <= target:
                    next_index = candidate_index
                    break
            start_index = max(start_index + 1, next_index)
        return chunks

    def _pdf_blocks(self, parsed: dict[str, Any]) -> list[dict[str, Any]]:
        if self._format(parsed) != "pdf":
            return []
        metadata = parsed.get("metadata")
        if not isinstance(metadata, dict):
            return []
        blocks = metadata.get("pdf_blocks")
        if not isinstance(blocks, list):
            return []
        return [
            block
            for block in blocks
            if isinstance(block, dict)
            and int(block.get("char_end", 0) or 0) > int(block.get("char_start", 0) or 0)
        ]

    def _pdf_chunk_metadata(
        self,
        start: int,
        end: int,
        blocks: list[dict[str, Any]],
        *,
        location_exact: bool,
    ) -> dict[str, Any]:
        """Attach block provenance or reject mixed page furniture."""
        if not blocks or not location_exact or end <= start:
            return {}
        overlaps = [
            block
            for block in blocks
            if max(start, int(block.get("char_start", 0) or 0))
            < min(end, int(block.get("char_end", 0) or 0))
        ]
        if not overlaps:
            return {"reject": True, "quality_flags": ["mixed_page_regions"]}

        kinds = {str(block.get("kind") or block.get("block_type") or "body") for block in overlaps}
        if kinds != {"body"}:
            flags: list[str] = []
            for block in overlaps:
                flags.extend(str(flag) for flag in block.get("quality_flags", []) if flag)
            if "mixed_page_regions" not in flags:
                flags.append("mixed_page_regions")
            return {"reject": True, "quality_flags": list(dict.fromkeys(flags))}

        pages = {int(block.get("page", 0) or 0) for block in overlaps}
        columns = {str(block.get("column") or "full_width") for block in overlaps}
        if len(pages) != 1 or len(columns) != 1:
            return {
                "reject": True,
                "quality_flags": ["mixed_page_regions"],
            }
        block = overlaps[0]
        return {
            "pdf_block_type": "body",
            "pdf_block_index": blocks.index(block),
            "pdf_column": next(iter(columns)),
            "pdf_reconstructed": any(bool(item.get("reconstructed")) for item in overlaps),
            "pdf_quality_flags": list(
                dict.fromkeys(
                    str(flag)
                    for item in overlaps
                    for flag in item.get("quality_flags", [])
                    if flag
                )
            ),
            "medical_evidence": True,
        }

    def _sentence_spans(self, text: str) -> list[tuple[int, int]]:
        """Return trimmed, punctuation-aware spans for stable chunk boundaries."""
        spans: list[tuple[int, int]] = []
        cursor = 0
        for match in self._SENTENCE_END.finditer(text):
            start, end, value = self._trim_range(text, cursor, match.end())
            if value:
                spans.append((start, end))
            cursor = match.end()
        start, end, value = self._trim_range(text, cursor, len(text))
        if value:
            spans.append((start, end))
        return spans

    def _table_parts(
        self,
        parsed: dict[str, Any],
        text: str,
        language: str,
        document_kind: str,
    ) -> tuple[list[StructuredSection], list[dict[str, Any]]]:
        sections: list[StructuredSection] = []
        chunks: list[dict[str, Any]] = []
        pages = self._page_ranges(parsed, text)
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
            section_chunks = self._section_chunks(section, document_kind, pages)
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
                self._section_chunks(section, document_kind, pages)
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
            "scope": "guideline_scope",
            "recommendations": "guideline_recommendation",
            "evidence": "guideline_evidence",
            "contraindications": "guideline_contraindication",
            "implementation": "guideline_implementation",
            "monitoring": "guideline_monitoring",
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
            "acknowledgements": "non_medical_metadata",
            "acknowledgments": "non_medical_metadata",
            "funding": "non_medical_metadata",
            "author_contributions": "non_medical_metadata",
            "conflicts_of_interest": "non_medical_metadata",
            "table": "table",
            "figure_caption": "figure_caption",
        }.get(section_type, "context")

    def _required_sections(self, document_kind: str) -> tuple[str, ...]:
        if document_kind == "guideline":
            return self.GUIDELINE_SECTIONS
        return self.REQUIRED_SECTIONS
