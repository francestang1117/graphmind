"""Pipeline tests for Module 2 -> Module 3 -> Module 4.

These tests keep the first graph-building pass grounded in the real flow:
Markdown parser output becomes entities, entities become graph nodes, and
relation hints become edges.
"""

from app.services.entity_extractor import EntityExtractor
from app.services.graph_builder_enhanced import KnowledgeGraph
from app.services.markdown_parser import MarkdownParser


SAMPLE_MARKDOWN = """# Machine Learning with Python

## Introduction

Machine learning uses Python. Python is popular for artificial intelligence.

## Frameworks

TensorFlow is developed by Google and used for deep learning.
PyTorch is created by Facebook AI Research.

```python
import tensorflow as tf
import pandas as pd
```

- [TensorFlow Official](https://tensorflow.org)
- [PyTorch Docs](https://pytorch.org)
"""


def test_markdown_entities_can_build_a_graph():
    parsed = MarkdownParser().parse_content(SAMPLE_MARKDOWN)
    extractor = EntityExtractor()

    entities = extractor.extract_from_markdown(parsed)
    relations = extractor.extract_relations(entities, parsed["raw_content"])

    graph = KnowledgeGraph()
    graph.add_document("ml-notes.md", entities, relations)
    stats = graph.get_stats()

    assert stats["total_nodes"] > 3
    assert stats["total_edges"] >= len(entities)
    assert stats["node_types"]["DOCUMENT"] == 1
    assert any(node["label"].lower() == "python" for node in graph.export_detailed()["nodes"])


def test_graph_merges_repeated_entities_across_documents():
    extractor = EntityExtractor()
    entities = extractor.extract_from_text("Python uses TensorFlow. Python uses pandas.")

    graph = KnowledgeGraph()
    graph.add_document("first.md", entities, [])
    graph.add_document("second.md", entities, [])

    python_nodes = [
        node
        for node in graph.export_detailed()["nodes"]
        if node["label"].lower() == "python"
    ]

    assert len(python_nodes) == 1
    assert set(python_nodes[0]["sources"]) == {"first.md", "second.md"}


def test_visualization_export_matches_frontend_shape():
    extractor = EntityExtractor()
    entities = extractor.extract_from_text("React uses JavaScript.")
    relations = extractor.extract_relations(entities, "React uses JavaScript.")

    graph = KnowledgeGraph()
    graph.add_document("frontend.md", entities, relations)
    visual = graph.export_for_visualization()

    assert {"nodes", "edges"} <= set(visual)
    assert all({"id", "label", "type", "size"} <= set(node) for node in visual["nodes"])
    assert all(isinstance(edge, tuple) and len(edge) == 2 for edge in visual["edges"])
    assert all({"source", "target", "type"} <= set(edge) for edge in visual["edge_details"])
    assert graph.get_stats()["edge_types"]["MENTIONS"] >= 2
