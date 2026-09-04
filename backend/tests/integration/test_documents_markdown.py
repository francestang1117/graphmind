"""Checks for the lightweight Markdown helper module."""

import importlib

import pytest

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
    assert summary["persistence_status"] == "cache_only"


def test_clear_cached_parse_is_idempotent():
    parse_markdown_bytes("test.md", SAMPLE_MD)

    clear_cached_parse("test.md")
    clear_cached_parse("test.md")

    assert get_cached_parse("test.md") is None


def test_latin1_markdown_still_parses():
    parsed = parse_markdown_bytes("latin.md", "# Cafe\n\ncaf\xe9".encode("latin-1"))

    assert parsed["title"] == "Cafe"


def test_parse_cache_is_published_only_after_persistence_succeeds(monkeypatch, tmp_path):
    parser_module = importlib.import_module(
        "app.api.endpoints.documents_with_markdown"
    )
    source = tmp_path / "paper.txt"
    source.write_text("A small document.", encoding="utf-8")

    class EmptyEntityExtractor:
        def extract_from_parsed_document(self, _parsed):
            return []

    class FailingArtifactRepository:
        def available(self):
            return True

        def replace_parse_bundle(self, *_args, **_kwargs):
            raise RuntimeError("database commit failed")

    monkeypatch.setattr(parser_module, "entity_extractor", EmptyEntityExtractor())
    monkeypatch.setattr(
        parser_module,
        "parsed_artifact_repository",
        FailingArtifactRepository(),
    )
    old_cached_result = {"version": "previous"}
    parser_module._parse_cache[parser_module.cache_key("paper.txt", "u1")] = (
        old_cached_result
    )

    with pytest.raises(parser_module.ParsePersistenceError):
        parser_module.parse_document_file(
            "paper.txt",
            str(source),
            user_id="u1",
            document_id="document-1",
        )

    assert parser_module.get_cached_parse("paper.txt", user_id="u1") is old_cached_result
