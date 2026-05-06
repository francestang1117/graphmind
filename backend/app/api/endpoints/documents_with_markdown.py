"""Parse cache and summary helpers for uploaded documents."""

from typing import Any, Optional

from app.services.document_parser import DocumentParser
from app.services.markdown_parser import MarkdownParser


_parse_cache: dict[str, dict[str, Any]] = {}


def cache_key(filename: str) -> str:
    return filename


def parse_markdown_bytes(filename: str, data: bytes) -> dict[str, Any]:
    """Parse Markdown bytes and store the result in a small local cache."""
    text = _decode_text(data)
    result = MarkdownParser().parse_content(text)
    _parse_cache[cache_key(filename)] = result
    return result


def parse_document_file(
    filename: str,
    file_path: str,
    original_filename: str = "",
) -> dict[str, Any]:
    """Parse any supported stored file and cache the normalized parser output."""
    result = DocumentParser().parse(file_path)
    metadata = result.setdefault("metadata", {})
    metadata["stored_filename"] = filename
    if original_filename:
        metadata["original_filename"] = original_filename
    _parse_cache[cache_key(filename)] = result
    return result


def get_cached_parse(filename: str) -> Optional[dict[str, Any]]:
    return _parse_cache.get(cache_key(filename))


def clear_cached_parse(filename: str) -> None:
    _parse_cache.pop(cache_key(filename), None)


def markdown_summary(filename: str, parsed: dict[str, Any]) -> dict[str, Any]:
    """Return the compact shape the UI will eventually consume."""
    metadata = parsed.get("metadata", {})
    return {
        "filename": filename,
        "title": parsed.get("title", "Untitled"),
        "headers_count": len(parsed.get("headers", [])),
        "sections_count": len(parsed.get("sections", [])),
        "links_count": len(parsed.get("links", [])),
        "images_count": len(parsed.get("images", [])),
        "code_blocks_count": len(parsed.get("code_blocks", [])),
        "word_count": metadata.get("word_count", 0),
        "reading_time": metadata.get("reading_time", 1),
        "has_code": metadata.get("has_code", False),
        "languages": metadata.get("languages", []),
    }


def document_summary(
    filename: str,
    parsed: dict[str, Any],
    original_filename: str = "",
) -> dict[str, Any]:
    """Return a compact, format-agnostic parse summary for the UI."""
    metadata = parsed.get("metadata", {})
    extra = parsed.get("extra", {})
    code_blocks = extra.get("code_blocks", [])
    imports = extra.get("imports", [])
    functions = extra.get("functions", [])
    classes = extra.get("classes", [])
    entities = extra.get("entities", [])
    languages = sorted(
        {
            block.get("language", "")
            for block in code_blocks
            if isinstance(block, dict) and block.get("language")
        }
    )

    return {
        "filename": filename,
        "title": original_filename or metadata.get("original_filename") or metadata.get("title") or filename,
        "format": metadata.get("format", ""),
        "headers_count": len(
            [
                section
                for section in extra.get("sections", [])
                if isinstance(section, dict) and section.get("level", 0) > 0
            ]
        ),
        "sections_count": len(extra.get("sections", [])),
        "chunks_count": len(parsed.get("chunks", [])),
        "links_count": len(extra.get("links", [])),
        "images_count": len(extra.get("images", [])),
        "list_items_count": len(extra.get("list_items", [])),
        "code_blocks_count": len(code_blocks),
        "tables_count": len(extra.get("tables", [])),
        "imports_count": len(imports),
        "functions_count": len(functions),
        "classes_count": len(classes),
        "entities_count": len(entities),
        "pages_count": metadata.get("pages", 0),
        "paragraphs_count": metadata.get("paragraph_count", 0),
        "comments_count": metadata.get("comments_count", 0),
        "inherited_styles_count": metadata.get("inherited_styles_count", 0),
        "word_count": metadata.get("word_count", 0),
        "reading_time": metadata.get("reading_time_min", 1),
        "has_code": bool(code_blocks or imports or functions or classes),
        "languages": languages,
        "imports": imports[:12],
        "functions": functions[:12],
        "classes": classes[:12],
        "entities": entities[:12],
    }


def _decode_text(data: bytes) -> str:
    for encoding in ("utf-8", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")
