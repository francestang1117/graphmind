"""Vector search tests for Module 5."""

from app.services.vector_store import VectorStore


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
