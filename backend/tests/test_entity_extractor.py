"""Entity extraction tests for the first graph-building module."""

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


def test_serializes_entities_and_relations():
    extractor = EntityExtractor()
    entities = extractor.extract_from_text("FastAPI uses Python.")
    relations = extractor.extract_relations(entities, "FastAPI uses Python.")

    assert entities[0].to_dict()["text"]
    assert relations[0].to_dict()["relation"]
