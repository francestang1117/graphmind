"""Markdown parser tests cover structure we surface later in search and graph views."""

from app.services.markdown_parser import MarkdownParser, _slug


def test_extracts_common_markdown_elements():
    content = """# Notes

                See [docs](https://example.com).

                ![Diagram](diagram.png)

                ```python
                print("hello")
                ```

                - first
                - second
            """

    result = MarkdownParser().parse_content(content)

    assert result["title"] == "Notes"
    assert result["headers"][0]["text"] == "Notes"
    assert result["links"] == [{"text": "docs", "url": "https://example.com", "line": 3}]
    assert result["images"][0]["alt"] == "Diagram"
    assert result["code_blocks"][0]["language"] == "python"
    assert [item["text"] for item in result["lists"]] == ["first", "second"]


def test_builds_nested_sections_from_headings():
    content = """# Guide

                Intro.

                ## Setup

                Install things.

                ### Local

                Run it locally.
            """

    sections = MarkdownParser().parse_content(content)["sections"]

    assert len(sections) == 1
    assert sections[0]["header"] == "Guide"
    assert sections[0]["subsections"][0]["header"] == "Setup"
    assert sections[0]["subsections"][0]["subsections"][0]["header"] == "Local"


def test_chunks_paragraphs_and_code_blocks():
    content = """# Title

                First paragraph.

                Second paragraph.

                ```js
                console.log("hi")
                ```
            """

    chunks = MarkdownParser().parse_content(content)["chunks"]
    types = [chunk["chunk_type"] for chunk in chunks]

    assert types.count("paragraph") == 2
    assert "header" in types
    assert "code" in types


def test_metadata_stays_small_and_useful():
    result = MarkdownParser().parse_content("One two three\n")

    assert result["metadata"]["word_count"] == 3
    assert result["metadata"]["reading_time"] == 1
    assert result["line_count"] == 1


def test_slug_normalises_headings_for_links():
    assert _slug("Hello, World!") == "hello-world"
