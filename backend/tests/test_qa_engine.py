"""QA engine tests for Module 6."""

from app.services.qa_engine import QAEngine


def test_local_answer_works_without_llm_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)

    engine = QAEngine()
    answer = engine._build_local_answer(
        "What uses FastAPI?",
        "[From: notes.md | Relevance: 77.0%]\nFastAPI uses Python to serve the API.",
        "No graph context available.",
    )

    assert "notes.md" in answer
    assert "FastAPI uses Python" in answer


def test_extract_sources_deduplicates_documents():
    engine = QAEngine()
    sources = engine._extract_sources(
        "\n".join(
            [
                "[From: notes.md | Relevance: 77.0%]",
                "text",
                "[From: notes.md | Relevance: 51.0%]",
                "[From: api.md | Relevance: 45.0%]",
            ]
        )
    )

    assert sources == [
        {"document": "notes.md", "relevance": "77.0%"},
        {"document": "api.md", "relevance": "45.0%"},
    ]


def test_main_concepts_answer_uses_compact_list():
    engine = QAEngine()
    answer = engine._build_local_answer(
        "What are the main concepts in my documents?",
        "[From: rag.md | Relevance: 80.0%]\nFastAPI uses Python for Semantic Search and Knowledge Graph workflows.",
        "- FastAPI (FRAMEWORK)\n- Knowledge Graph (CONCEPT)",
    )

    assert "Main concepts I found:" in answer
    assert "- FastAPI" in answer
    assert "FastAPI uses Python for Semantic Search" not in answer


def test_safe_excerpt_does_not_cut_mid_word_when_possible():
    engine = QAEngine()
    excerpt = engine._safe_excerpt(" ".join(["retrieval"] * 80), max_len=80)

    assert excerpt.endswith("...")
    assert not excerpt.endswith("retr...")


def test_framework_question_uses_entity_summary_not_raw_chunks():
    engine = QAEngine()
    answer = engine._build_local_answer(
        "Which frameworks appear most often?",
        "[From: assignment.docx | Relevance: 20.0%]\nThese sketches should reflect different ideas.",
        "- FastAPI (FRAMEWORK)\n- React (FRAMEWORK)\n- Python (PROGRAMMING_LANGUAGE)",
    )

    assert "Frameworks and libraries I found most often:" in answer
    assert "- FastAPI:" in answer
    assert "These sketches should reflect" not in answer


def test_json_document_summary_uses_fields_not_raw_metadata_dump():
    engine = QAEngine()
    summary = engine._summarize_parsed_document(
        "about.json",
        {
            "metadata": {"format": "json", "title": "about.json"},
            "chunks": [
                {
                    "text": "channels: array[1]\nconda_build_version: 3.21.4\ndev_url: https://github.com/example/project",
                    "type": "schema",
                }
            ],
            "extra": {},
        },
    )

    assert summary == "about.json: JSON data/metadata with fields such as channels, conda_build_version, dev_url"


def test_collection_summary_intent_is_detected():
    engine = QAEngine()

    assert engine._asks_for_collection_summary("Summarize the key ideas across all files")


def test_named_document_matching_uses_filename_tokens():
    engine = QAEngine()

    assert engine._content_tokens("tell me the main content of rag system design") & engine._content_tokens("RAG System Design.md")
    assert not (engine._content_tokens("tell me the main content of rag system design") & engine._content_tokens("A2_Instructions_2023.docx"))


def test_single_document_summary_is_structured():
    engine = QAEngine()
    answer = engine._summarize_single_document(
        "RAG System Design.md",
        {
            "metadata": {"format": "md", "title": "RAG System Design"},
            "chunks": [
                {"text": "React frontend sends questions to a FastAPI backend. FastAPI uses Python to parse uploaded Markdown documents."}
            ],
            "extra": {"entities": [{"text": "React"}, {"text": "FastAPI"}, {"text": "Python"}]},
        },
    )

    assert "Type: MD" in answer
    assert "Key terms: React, FastAPI, Python" in answer
    assert "React frontend sends questions" in answer
