"""Markdown helpers for the document module.

This file is intentionally not registered as a separate router yet. It keeps
the Module 2 parsing work small and importable while the main upload endpoints
stay focused on storage.

Implemented:
- parse Markdown bytes from upload background work
- keep a lightweight parse cache
- return compact summary data for the frontend viewer
- clear cached parse data when a file is deleted
"""

from typing import Any, Optional

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


def _decode_text(data: bytes) -> str:
    for encoding in ("utf-8", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")
