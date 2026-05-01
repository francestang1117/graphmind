"""Entity extraction tests for the first graph-building module."""

from app.services import entity_extractor as extractor_module
from app.services.entity_extractor import EntityExtractor
from app.services.markdown_parser import MarkdownParser


def texts(entities):
    return {entity.normalized or entity.text for entity in entities}


def labels(entities):
    return {entity.label for entity in entities}


def test_extracts_technical_entities_without_spacy_model():
    # The MVP must work without a downloaded spaCy model; rules are the stable
    # baseline for local development and CI.
    extractor = EntityExtractor()

    entities = extractor.extract_from_text(
        "React uses JavaScript. The backend uses Python, FastAPI, TensorFlow, and PyTorch."
    )

    found = texts(entities)
    assert {"react", "javascript", "python", "fastapi", "tensorflow", "pytorch"} <= {
        item.lower() for item in found
    }
    assert {"FRAMEWORK", "PROGRAMMING_LANGUAGE"} <= labels(entities)


def test_default_constructor_attempts_spacy_without_requiring_it(monkeypatch):
    calls = []

    def fake_loader(self, model_name):
        calls.append(model_name)
        return None

    monkeypatch.setattr(EntityExtractor, "_load_spacy_model", fake_loader)

    extractor = EntityExtractor()

    assert calls == ["en_core_web_sm"]
    assert extractor.nlp is None


def test_spacy_loader_uses_model_cache(monkeypatch):
    sentinel_model = object()
    monkeypatch.setitem(extractor_module._SPACY_MODEL_CACHE, "cached_model", sentinel_model)

    extractor = EntityExtractor(model_name="cached_model")

    assert extractor.nlp is sentinel_model


def test_extracts_markdown_context_entities():
    # Headings, links, and fenced-code imports should add context that plain
    # text extraction would otherwise miss.
    parsed = MarkdownParser().parse_content(
        """# Machine Learning

## Python Setup

- TensorFlow
- PyTorch

```python
import tensorflow as tf
import numpy as np
```

[FastAPI](https://fastapi.tiangolo.com)
"""
    )
    entities = EntityExtractor().extract_from_markdown(parsed)
    found = {item.lower() for item in texts(entities)}

    assert "machine learning" in found
    assert "python setup" in found
    assert "tensorflow" in found
    assert "numpy" in found
    assert "fastapi" in found


def test_js_relative_imports_do_not_become_dependencies():
    parsed = MarkdownParser().parse_content(
        """# Frontend

```javascript
import helper from './_shuffleSelf';
import React from 'react';
```
"""
    )

    entities = EntityExtractor().extract_from_markdown(parsed)
    found = {item.lower() for item in texts(entities)}

    assert "react" in found
    assert "./_shuffleself" not in found


def test_aliases_merge_to_canonical_entities():
    entities = EntityExtractor().extract_from_text("JS and JavaScript both use JSON over HTTP.")
    found = {entity.normalized for entity in entities}

    assert "JavaScript" in found
    assert "JS" not in found
    assert "JSON" in found
    assert "HTTP" in found


def test_domain_vocabulary_extracts_curated_terms():
    entities = EntityExtractor().extract_from_text(
        "The app uses RAG with a vector database, semantic search, LLMs, and reranking."
    )
    found = {entity.normalized for entity in entities}

    assert "Retrieval Augmented Generation" in found
    assert "Vector Database" in found
    assert "Semantic Search" in found
    assert "Large Language Model" in found
    assert "Reranking" in found


def test_domain_entities_collapse_duplicate_spacy_labels():
    extractor = EntityExtractor(model_name=None)
    entities = extractor._deduplicate(
        [
            extractor._entity("Python", "LANGUAGE", 0, 6, 0.82, "spacy"),
            extractor._entity("python", "PROGRAMMING_LANGUAGE", 0, 6, 0.94, "domain"),
        ]
    )

    python_entities = [entity for entity in entities if entity.normalized == "Python"]

    assert len(python_entities) == 1
    assert python_entities[0].label == "PROGRAMMING_LANGUAGE"


def test_overlapping_domain_terms_prefer_specific_phrase():
    entities = EntityExtractor().extract_from_text(
        "The retrieval pipeline stores vector embeddings for semantic search."
    )
    found = {entity.normalized for entity in entities}

    assert "Vector Embedding" in found
    assert "Embedding" not in found


def test_filters_common_spacy_and_parser_noise():
    extractor = EntityExtractor(model_name=None)
    noisy = [
        extractor._entity("3.8.10 h12debd9_8 python", "PRODUCT", 0, 25, 0.82, "spacy"),
        extractor._entity("he6710b0_3", "PRODUCT", 0, 10, 0.82, "spacy"),
        extractor._entity("Wednesday, June. 21", "DATE", 0, 18, 0.82, "spacy"),
        extractor._entity("11:00pm", "TIME", 0, 7, 0.82, "spacy"),
        extractor._entity("10+", "CARDINAL", 0, 3, 0.82, "spacy"),
        extractor._entity("New York City's", "LOCATION", 0, 15, 0.82, "spacy"),
        extractor._entity("New York City", "LOCATION", 0, 13, 0.82, "spacy", "New York City uses React."),
        extractor._entity("jargon", "CONCEPT", 0, 6, 0.82, "spacy"),
        extractor._entity("Generate", "CONCEPT", 0, 8, 0.82, "spacy"),
        extractor._entity("Halifax", "LOCATION", 0, 7, 0.82, "spacy"),
        extractor._entity("Python", "PROGRAMMING_LANGUAGE", 0, 6, 0.94, "domain"),
    ]
    found = {entity.normalized for entity in extractor._deduplicate(noisy)}

    assert found == {"Python"}


def test_single_word_context_fragments_are_filtered_unless_domain_terms():
    extractor = EntityExtractor(model_name=None)
    entities = extractor._deduplicate(
        [
            extractor._entity("Method", "CONCEPT", 0, 6, 0.72, "context"),
            extractor._entity("Generate", "CONCEPT", 0, 8, 0.72, "context"),
            extractor._entity("Markdown", "CONCEPT", 0, 8, 0.94, "domain"),
            extractor._entity("Knowledge Graph", "CONCEPT", 0, 15, 0.72, "context"),
        ]
    )
    found = {entity.normalized for entity in entities}

    assert found == {"Markdown", "Knowledge Graph"}


def test_confidence_filter_blocks_weak_llm_entities():
    def fake_llm(_text: str):
        return [
            {"text": "Random Phrase", "type": "CONCEPT", "confidence": 0.42},
            {"text": "Useful Concept", "type": "CONCEPT", "confidence": 0.82},
        ]

    entities = EntityExtractor(llm_enhancer=fake_llm).extract_from_text(
        "This text is long enough to let the optional LLM enhancer run."
    )
    found = {entity.text for entity in entities}

    assert "Useful Concept" in found
    assert "Random Phrase" not in found


def test_optional_relation_enhancer_adds_llm_style_relations():
    def fake_relation_enhancer(_entities, _text):
        return [
            {"source": "RAG", "target": "Vector Database", "relation": "USES", "confidence": 0.86},
        ]

    extractor = EntityExtractor(model_name=None, relation_enhancer=fake_relation_enhancer)
    entities = extractor.extract_from_text("RAG uses a vector database.")
    relations = extractor.extract_relations(entities, "RAG uses a vector database.")
    triples = {(relation.source, relation.relation, relation.target) for relation in relations}

    assert ("RAG", "USES", "Vector Database") in triples


def test_llm_enhancer_is_optional_and_dependency_free():
    entities = EntityExtractor().extract_from_text(
        "Semantic search connects documents to a knowledge graph."
    )
    found = {entity.normalized for entity in entities}

    assert "Semantic Search" in found
    assert "Knowledge Graph" in found


def test_parser_symbols_keep_function_but_do_not_create_generic_word_nodes():
    parsed = {
        "content": "",
        "extra": {
            "functions": ["_arraySampleSize(items)"],
            "classes": [],
            "imports": [],
            "code_blocks": [],
            "sections": [],
            "entities": [],
        },
    }

    entities = EntityExtractor().extract_from_parsed_document(parsed)
    found = {entity.normalized for entity in entities}

    assert "arraySampleSize" in found
    assert "Array" not in found
    assert "Sample" not in found
    assert "Size" not in found


def test_deduplicates_entities_across_sources():
    extractor = EntityExtractor()

    entities = extractor.extract_from_text("Python works with python and PYTHON.")
    python_entities = [
        entity for entity in entities if (entity.normalized or entity.text).lower() == "python"
    ]

    assert len(python_entities) == 1
    assert python_entities[0].confidence >= 0.9


def test_extracts_relation_hints():
    # These are relation hints for the graph builder, not deep NLP claims.
    extractor = EntityExtractor()
    text = "React uses JavaScript. Python uses TensorFlow."

    entities = extractor.extract_from_text(text)
    relations = extractor.extract_relations(entities, text)
    triples = {(rel.source.lower(), rel.relation, rel.target.lower()) for rel in relations}

    assert ("react", "USES", "javascript") in triples
    assert ("python", "USES", "tensorflow") in triples


def test_same_sentence_type_pairs_add_weak_relations():
    extractor = EntityExtractor(model_name=None)
    text = "FastAPI and Python power the API layer."

    entities = extractor.extract_from_text(text)
    relations = extractor.extract_relations(entities, text)
    triples = {(rel.source, rel.relation, rel.target, rel.confidence) for rel in relations}

    assert ("FastAPI", "WRITTEN_IN", "Python", 0.52) in triples


def test_non_geography_locations_are_blocked_but_domain_entities_remain():
    extractor = EntityExtractor(model_name=None)
    entities = extractor._deduplicate(
        [
            extractor._entity("Halifax", "LOCATION", 0, 7, 0.82, "spacy", "The parser mentions FastAPI and JSON."),
            extractor._entity("FastAPI", "FRAMEWORK", 0, 7, 0.94, "domain"),
        ]
    )
    found = {entity.normalized for entity in entities}

    assert found == {"FastAPI"}


def test_optional_semantic_similarity_merges_near_duplicate_entities():
    def fake_similarity(left: str, right: str) -> float:
        pair = {left.lower(), right.lower()}
        return 0.95 if pair == {"retrieval augmented generation", "rag system"} else 0.1

    extractor = EntityExtractor(model_name=None, semantic_similarity=fake_similarity)
    entities = extractor._deduplicate(
        [
            extractor._entity("Retrieval Augmented Generation", "CONCEPT", 0, 30, 0.94, "domain"),
            extractor._entity("RAG System", "CONCEPT", 0, 10, 0.78, "llm"),
        ]
    )

    assert [entity.normalized for entity in entities] == ["Retrieval Augmented Generation"]


def test_serializes_entities_and_relations():
    extractor = EntityExtractor()
    entities = extractor.extract_from_text("FastAPI uses Python.")
    relations = extractor.extract_relations(entities, "FastAPI uses Python.")

    assert entities[0].to_dict()["text"]
    assert relations[0].to_dict()["relation"]
