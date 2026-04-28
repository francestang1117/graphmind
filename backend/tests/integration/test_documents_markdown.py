"""Checks for the lightweight Markdown helper module."""

from app.api.endpoints.documents_with_markdown import (
    _parse_cache,
    clear_cached_parse,
    get_cached_parse,
    markdown_summary,
    parse_markdown_bytes,
)


SAMPLE_MD = b"""# Test Document

See [docs](https://example.com).

```python
print("hello")
```
"""


def setup_function():
    _parse_cache.clear()


def test_parse_markdown_bytes_caches_result():
    parsed = parse_markdown_bytes("test.md", SAMPLE_MD)

    assert parsed["title"] == "Test Document"
    assert get_cached_parse("test.md") == parsed


def test_markdown_summary_keeps_only_ui_friendly_fields():
    parsed = parse_markdown_bytes("test.md", SAMPLE_MD)
    summary = markdown_summary("test.md", parsed)

    assert summary["filename"] == "test.md"
    assert summary["title"] == "Test Document"
    assert summary["links_count"] == 1
    assert summary["has_code"] is True
    assert summary["languages"] == ["python"]


def test_clear_cached_parse_is_idempotent():
    parse_markdown_bytes("test.md", SAMPLE_MD)

    clear_cached_parse("test.md")
    clear_cached_parse("test.md")

    assert get_cached_parse("test.md") is None


def test_latin1_markdown_still_parses():
    parsed = parse_markdown_bytes("latin.md", "# Cafe\n\ncaf\xe9".encode("latin-1"))

    assert parsed["title"] == "Cafe"
