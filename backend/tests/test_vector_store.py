"""Vector search tests for Module 5."""

from app.services.vector_store import VectorStore, compact_excerpt, markdown_for_excerpt, searchable_chunk_text


def test_hybrid_search_finds_relevant_chunk():
    store = VectorStore()
    store.add_chunks(
        [
            {"text": "Python is used with FastAPI to build REST APIs.", "type": "section"},
            {"text": "Graph layout controls make nodes easier to explore.", "type": "section"},
        ],
        "notes.md",
    )

    results = store.hybrid_search("python api", 2)

    assert results
    assert results[0]["document"] == "notes.md"
    assert "Python" in results[0]["excerpt"]
    assert results[0]["score"] > 0


def test_alias_tokens_help_js_queries_match_javascript():
    store = VectorStore()
    store.add_chunks(
        [{"text": "JavaScript modules can import React components.", "type": "code"}],
        "frontend.ts",
    )

    results = store.hybrid_search("js react", 1)

    assert results
    assert results[0]["source"] == "frontend.ts"


def test_context_for_qa_includes_sources():
    store = VectorStore()
    store.add_chunks([{"text": "TensorFlow is a machine learning framework."}], "ml.md")

    context = store.get_context_for_qa("machine learning")

    assert "ml.md" in context
    assert "TensorFlow" in context


def test_excerpt_starts_near_query_without_breaking_markdown_links():
    text = (
        "Intro text before the useful part. "
        "The same site also contains distributions of and pointers to many free "
        "third party [Python modules](https://www.python.org/) and tools."
    )

    excerpt = compact_excerpt(text, max_len=110, query="python modules")

    assert "Python modules (https://www.python.org/)" in excerpt
    assert "](https://" not in excerpt
    assert excerpt.endswith("...") or excerpt.startswith("...")


def test_markdown_links_are_readable_in_search_excerpts():
    text = "See [The Python Standard Library](https://docs.python.org/3/library/) for details."

    assert markdown_for_excerpt(text) == (
        "See The Python Standard Library (https://docs.python.org/3/library/) for details."
    )


def test_source_only_lines_do_not_become_search_results():
    store = VectorStore()
    added = store.add_chunks(
        [
            {"text": "Source: https://docs.python.org/3/tutorial/index.html", "type": "section"},
            {
                "text": (
                    "Source: https://docs.python.org/3/tutorial/index.html\n\n"
                    "Python modules and packages are covered in this tutorial."
                ),
                "type": "section",
            },
        ],
        "python-tutorial.md",
    )

    assert added == 1
    indexed_text = next(iter(store.chunks.values())).text
    assert indexed_text == "Python modules and packages are covered in this tutorial."
    assert searchable_chunk_text("Source: https://example.com") == ""
