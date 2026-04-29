"""Small Markdown structure parser used by the document pipeline.

Implemented:
- title and heading extraction
- link and image extraction
- fenced code block extraction
- ordered and unordered list detection
- nested section tree
- paragraph/header/code chunking
- word count, reading time, and language metadata
"""

from dataclasses import dataclass, field
import re
from typing import Any, Dict, List


@dataclass
class Header:
    level: int
    text: str
    line: int
    id: str

@dataclass
class Link:
    text: str
    url: str
    line: int

    def to_dict(self) -> Dict[str, Any]:
        return {"text": self.text, "url": self.url, "line": self.line}

@dataclass
class Image:
    alt: str
    url: str
    line: int

    def to_dict(self) -> Dict[str, Any]:
        return {"alt":  self.alt, "url": self.url, "line": self.line}
    
@dataclass
class CodeBlock:
    language: str
    code: str
    line: int

    def to_dict(self) -> Dict[str, Any]:
        return {"language": self.language, "code": self.code, "line": self.line}

@dataclass
class ListItem:
    text: str
    level: int
    is_ordered: bool
    line: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text,
            "level": self.level,
            "is_ordered": self.is_ordered,
            "line": self.line
        }
    
@dataclass
class Section:
    header: str
    level: int
    content: str
    start_line: int
    end_line: int
    subsections: List["Section"] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "header": self.header,
            "level": self.level,
            "content": self.content,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "subsections": [s.to_dict() for s in self.subsections]
        }

@dataclass 
class Chunk:
    text: str
    chunk_type: str
    metadata: Dict[str, Any]
    start_line: int
    end_line: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text,
            "chunk_type": self.chunk_type,
            "metadata": self.metadata,
            "start_line": self.start_line,
            "end_line": self.end_line
        }
    
_RE_HEADER = re.compile(r"^(#{1,6})\s+(.+)$")
_RE_LINK = re.compile(r"(?<!!)\[([^\]]+)\]\(([^)]+)\)")
_RE_IMAGE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
_RE_CODE_FENCE = re.compile(r"^```(\w*)\s*$")
_RE_LIST_ITEM = re.compile(r"^(\s*)([-*+]|\d+\.)\s+(.+)$")
_RE_BLOCKQUOTE = re.compile(r"^>\s+(.+)$", re.MULTILINE)

class MarkdownParser:
    """Parse decoded Markdown text into lightweight structure."""

    def parse_content(self, content: str) -> Dict[str, Any]:
        """Return headers, links, sections, chunks, and metadata."""
        # Tests and pasted snippets often carry editor indentation; normalize that
        # before matching Markdown syntax so headings/fences/lists still parse.
        lines = [line.lstrip() for line in content.splitlines()]
        content = "\n".join(lines)

        headers = self._extract_headers(lines)
        links = self._extract_links(lines)
        images = self._extract_images(lines)
        code_blocks = self._extract_code_blocks(lines)
        list_items  = self._extract_lists(lines)
        sections    = self._build_sections(lines, headers)
        chunks      = self._chunk_content(lines)
        metadata    = self._extract_metadata(content, code_blocks)
        title       = self._extract_title(headers)

        return {
            "title":       title,
            "headers":     [self._header_to_dict(h) for h in headers],
            "sections":    [s.to_dict() for s in sections],
            "links":       [l.to_dict() for l in links],
            "images":      [i.to_dict() for i in images],
            "code_blocks": [c.to_dict() for c in code_blocks],
            "lists":       [li.to_dict() for li in list_items],
            "chunks":      [c.to_dict() for c in chunks],
            "metadata":    metadata,
            "raw_content": content,
            "line_count":  len(lines),
        }
    

    def _extract_headers(self, lines: List[str]) -> List[Header]:
        headers: List[Header] = []
        for line_num, line in enumerate(lines, start=1):
            m = _RE_HEADER.match(line)
            if m:
                level = len(m.group(1))
                text  = m.group(2).strip()
                headers.append(Header(
                    level=level,
                    text=text,
                    line=line_num,
                    id=_slug(text),
                ))
        return headers


    def _extract_links(self, lines: List[str]) -> List[Link]:
        links: List[Link] = []
        for line_num, line in enumerate(lines, start=1):
            for m in _RE_LINK.finditer(line):
                links.append(Link(text=m.group(1), url=m.group(2), line=line_num))
        return links

    def _extract_images(self, lines: List[str]) -> List[Image]:
        images: List[Image] = []
        for line_num, line in enumerate(lines, start=1):
            for m in _RE_IMAGE.finditer(line):
                images.append(Image(
                    alt=m.group(1) or "image",
                    url=m.group(2),
                    line=line_num,
                ))
        return images
    
    def _extract_code_blocks(self, lines: List[str]) -> List[CodeBlock]:
        code_blocks: List[CodeBlock] = []
        in_block    = False
        language    = ""
        block_lines: List[str] = []
        start_line  = 0
 
        for line_num, line in enumerate(lines, start=1):
            m = _RE_CODE_FENCE.match(line)
            if m and not in_block:
                in_block   = True
                language   = m.group(1) or ""
                block_lines = []
                start_line = line_num
            elif in_block and line.strip() == "```":
                code_blocks.append(CodeBlock(
                    language=language,
                    code="\n".join(block_lines),
                    line=start_line,
                ))
                in_block    = False
                block_lines = []
            elif in_block:
                block_lines.append(line)
 
        return code_blocks
    
    def _extract_lists(self, lines: List[str]) -> List[ListItem]:
        items: List[ListItem] = []
        for line_num, line in enumerate(lines, start=1):
            m = _RE_LIST_ITEM.match(line)
            if m:
                indent     = m.group(1)
                marker     = m.group(2)
                text       = m.group(3)
                level      = len(indent) // 2
                is_ordered = marker[0].isdigit()
                items.append(ListItem(
                    text=text,
                    level=level,
                    is_ordered=is_ordered,
                    line=line_num,
                ))
        return items
    
    def _build_sections(
        self, lines: List[str], headers: List[Header]
    ) -> List[Section]:    
        if not headers:
            return []
 
        flat: List[Section] = []
        for i, header in enumerate(headers):
            end_line = headers[i + 1].line - 1 if i < len(headers) - 1 else len(lines)
            content_lines = lines[header.line : end_line]
            content = "\n".join(content_lines).strip()
 
            flat.append(Section(
                header=header.text,
                level=header.level,
                content=content,
                start_line=header.line,
                end_line=end_line,
            ))
 
        return _nest_sections(flat)
    
    def _chunk_content(
        self,
        lines: List[str],
        max_chunk_chars: int = 1000,
    ) -> List[Chunk]:
        """Walk the document line-by-line and emit typed chunks."""
        chunks: List[Chunk] = []
        current: List[str] = []
        current_type = "paragraph"
        start_line   = 1
 
        in_code      = False
        code_lang    = ""
        code_start   = 0
 
        def flush(end: int) -> None:
            text = "\n".join(current).strip()
            if text:
                chunks.append(Chunk(
                    text=text,
                    chunk_type=current_type,
                    metadata={},
                    start_line=start_line,
                    end_line=end,
                ))
            current.clear()
 
        for line_num, line in enumerate(lines, start=1):
            m_fence = _RE_CODE_FENCE.match(line)
            if m_fence and not in_code:
                flush(line_num - 1)
                in_code   = True
                code_lang = m_fence.group(1) or ""
                code_start = line_num
                continue
 
            if in_code:
                if line.strip() == "```":
                    code_text = "\n".join(current).strip()
                    if code_text:
                        chunks.append(Chunk(
                            text=code_text,
                            chunk_type="code",
                            metadata={"language": code_lang},
                            start_line=code_start,
                            end_line=line_num,
                        ))
                    current.clear()
                    in_code = False
                else:
                    current.append(line)
                continue

            if _RE_HEADER.match(line):
                flush(line_num - 1)
                level = len(line.split()[0])
                chunks.append(Chunk(
                    text=line,
                    chunk_type="header",
                    metadata={"level": level},
                    start_line=line_num,
                    end_line=line_num,
                ))
                start_line = line_num + 1
                current_type = "paragraph"
                continue

            if not line.strip():
                flush(line_num - 1)
                start_line = line_num + 1
                continue

            current.append(line)
 
            if len("\n".join(current)) > max_chunk_chars:
                flush(line_num)
                start_line = line_num + 1
 
        flush(len(lines))
        return chunks

    def _extract_metadata(self, content: str, code_blocks: List[CodeBlock]) -> Dict[str, Any]:
        words      = content.split()
        word_count = len(words)
        reading_time = max(1, round(word_count / 250))
        languages = list({b.language for b in code_blocks if b.language})
 
        return {
            "word_count":        word_count,
            "reading_time":      reading_time,
            "has_code":          bool(code_blocks),
            "has_links":         bool(_RE_LINK.search(content)),
            "has_images":        bool(_RE_IMAGE.search(content)),
            "has_blockquotes":   bool(_RE_BLOCKQUOTE.search(content)),
            "languages":         languages,
            "code_blocks_count": len(code_blocks),
        }
    
    def _extract_title(self, headers: List[Header]) -> str:
        """Return the text of the first H1, or 'Untitled'."""
        for h in headers:
            if h.level == 1:
                return h.text
        return "Untitled"
 
    @staticmethod
    def _header_to_dict(h: Header) -> Dict[str, Any]:
        return {"level": h.level, "text": h.text, "line": h.line, "id": h.id}

def _slug(text: str) -> str:
    slug = text.lower()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    return slug.strip("-")

def _nest_sections(flat: List[Section]) -> List[Section]:
    roots: List[Section] = []
    stack: List[Section] = []
 
    for section in flat:
        while stack and stack[-1].level >= section.level:
            stack.pop()
 
        if stack:
            stack[-1].subsections.append(section)
        else:
            roots.append(section)
 
        stack.append(section)
 
    return roots
