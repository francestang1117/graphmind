"""Parse supported document formats into text, chunks, and metadata."""

from pathlib import Path
import ast
import re
from typing import Any, Dict, List

from docx import Document
import markdown
from PyPDF2 import PdfReader


class UnsupportedFileTypeError(ValueError):
    """Raised when no parser is registered for a file extension."""


class DocumentParser:
    
    def __init__(self):
        self.parsers = {
            ".md": self._parse_markdown,
            ".txt": self._parse_text,
            ".pdf": self._parse_pdf,
            ".docx": self._parse_docx,
            ".py": self._parse_code,
            ".js": self._parse_code,
            ".ts": self._parse_code
        }

    def parse(self, file_path: str) -> Dict[str, Any]:
        """Parse a file path into a common result shape."""
        path = Path(file_path)
        ext = path.suffix.lower()

        if ext not in self.parsers:
            raise UnsupportedFileTypeError(f"Unsupported file type: {ext}")
        
        return self.parsers[ext](path)

    def _parse_markdown(self, path: Path) -> Dict[str, Any]:
        content = path.read_text(encoding="utf-8")
        html_content = markdown.markdown(content)

        chunks = self._chunk_text(content, source=path)

        return self._build_result(
             content=content,
             chunks=chunks,
             path=path,
             format="markdown",
             extra={
                 "html": html_content,
                 "headings": self._extract_markdown_headings(content),
                 "links": self._extract_markdown_links(content),
                 "code_blocks": self._extract_markdown_code_blocks(content),
             }
        )

    def _parse_text(self, path: Path) -> Dict[str, Any]:
        content = path.read_text(encoding="utf-8")
        chunks = self._chunk_text(content, source=path)

        return self._build_result(
            content=content,
            chunks=chunks,
            path=path,
            format="text"
        )
    
    def _parse_pdf(self, path: Path) -> Dict[str, Any]:
        reader = PdfReader(str(path))

        content = ""
        for page in reader.pages:
            text = page.extract_text() or ""
            content += text + "\n\n"

        chunks = self._chunk_text(content, source=path)

        return self._build_result(
            content=content,
            chunks=chunks,
            path=path,
            format="pdf",
            extra={"pages": len(reader.pages)},
        )
    
    def _parse_docx(self, path: Path) -> Dict[str, Any]:

        doc = Document(path)
        content = "\n".join(p.text for p in doc.paragraphs if p.text.strip())

        chunks = self._chunk_text(content, source=path)

        return self._build_result(
            content=content,
            chunks=chunks,
            path=path,
            format="docx",
        )
    
    def _parse_code(self, path: Path) -> Dict[str, Any]:
        content = path.read_text(encoding="utf-8")

        chunks = self._chunk_text(content, chunk_size=500, source=path)
        suffix = path.suffix.lower()
        symbols = self._extract_python_symbols(content) if suffix == ".py" else self._extract_js_symbols(content)

        return self._build_result(
            content=content,
            chunks=chunks,
            path=path,
            format="code",
            extra={
                "language": suffix[1:],
                "symbols": symbols,
                "imports": self._extract_imports(content, suffix),
                "comments": self._extract_comments(content, suffix),
            },
        )
        
    def _chunk_text(
            self, 
            text: str,
            chunk_size: int = 1000,
            overlap: int = 200,
            source: Path = None
    ) -> List[Dict[str, Any]]:
        """Chunk text by paragraphs."""
        paragraphs = re.split(r"\n\s*\n", text)

        chunks = []
        current = ""
        idx = 0

        for para in paragraphs:
            if len(current) + len(para) < chunk_size:
                current += para + "\n\n"
            else:
                if current.strip():
                    chunks.append(self._build_chunk(current, idx, source))
                    idx += 1
                current = para

        if current.strip():
            chunks.append(self._build_chunk(current, idx, source))
        
        return chunks

    def _build_chunk(self, text: str, idx: int, source: Path) -> Dict[str, Any]:
        return {
            "id": f"{source.stem}_chunk_{idx}" if source else f"chunk_{idx}",
            "text": text.strip(),
            "length": len(text),
        }

    def _extract_markdown_headings(self, text: str) -> List[Dict[str, Any]]:
        headings = []
        for match in re.finditer(r"^(#{1,6})\s+(.+)$", text, re.MULTILINE):
            headings.append({
                "level": len(match.group(1)),
                "text": match.group(2).strip(),
            })
        return headings

    def _extract_markdown_links(self, text: str) -> List[Dict[str, str]]:
        return [
            {"text": match.group(1), "url": match.group(2)}
            for match in re.finditer(r"\[([^\]]+)\]\(([^)]+)\)", text)
        ]

    def _extract_markdown_code_blocks(self, text: str) -> List[Dict[str, str]]:
        blocks = []
        for match in re.finditer(r"```(\w+)?\n(.*?)```", text, re.DOTALL):
            blocks.append({
                "language": match.group(1) or "",
                "code": match.group(2).strip(),
            })
        return blocks

    def _extract_python_symbols(self, text: str) -> List[Dict[str, Any]]:
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return []

        symbols = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                symbols.append({
                    "name": node.name,
                    "type": "class" if isinstance(node, ast.ClassDef) else "function",
                    "line": node.lineno,
                })
        return sorted(symbols, key=lambda item: item["line"])

    def _extract_js_symbols(self, text: str) -> List[Dict[str, Any]]:
        patterns = [
            ("class", r"\bclass\s+([A-Za-z_$][\w$]*)"),
            ("function", r"\bfunction\s+([A-Za-z_$][\w$]*)\s*\("),
            ("function", r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\("),
        ]
        symbols = []
        for symbol_type, pattern in patterns:
            for match in re.finditer(pattern, text):
                symbols.append({
                    "name": match.group(1),
                    "type": symbol_type,
                    "line": text.count("\n", 0, match.start()) + 1,
                })
        return sorted(symbols, key=lambda item: item["line"])

    def _extract_imports(self, text: str, suffix: str) -> List[str]:
        if suffix == ".py":
            return re.findall(r"^(?:from\s+\S+\s+import\s+.+|import\s+.+)$", text, re.MULTILINE)
        return re.findall(r"^(?:import\s+.+|export\s+.+from\s+.+|const\s+\S+\s*=\s*require\(.+\).*)$", text, re.MULTILINE)

    def _extract_comments(self, text: str, suffix: str) -> List[str]:
        if suffix == ".py":
            return [match.group(1).strip() for match in re.finditer(r"^\s*#\s?(.*)$", text, re.MULTILINE)]
        return [match.group(1).strip() for match in re.finditer(r"^\s*//\s?(.*)$", text, re.MULTILINE)]

    def _build_result(
            self, 
            content: str, 
            chunks: List[Dict[str, Any]],
            path: Path,
            format: str,
            extra: Dict[str, Any] = None
        ) -> Dict[str, Any]: 
            stat = path.stat()

            return {
                 "content": content,
                 "chunks": chunks,
                 "metadata": {
                      "filename": path.name,
                      "format": format,
                      "size": stat.st_size,
                      "num_chunks": len(chunks)
                 },
                 "extra": extra or {}
            }
