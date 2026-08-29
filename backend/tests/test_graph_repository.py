"""Graph repository tests."""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.services.graph_repository import GraphRepository


def _repo() -> GraphRepository:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    return GraphRepository(session_factory=session_factory, enabled=lambda: True)


def test_graph_repository_replaces_one_document_slice():
    repo = _repo()

    repo.replace_document_graph(
        user_id="u1",
        document_id="doc-a.md",
        graph={
            "nodes": [
                {"id": "doc_a", "label": "A.md", "type": "DOCUMENT", "sources": ["A.md"]},
                {"id": "python", "label": "Python", "type": "PROGRAMMING_LANGUAGE", "sources": ["A.md"]},
            ],
            "edges": [
                {
                    "source": "doc_a",
                    "target": "python",
                    "type": "USES",
                    "weight": 1,
                    "confidence": 0.9,
                    "sources": ["A.md"],
                }
            ],
        },
    )
    repo.replace_document_graph(
        user_id="u1",
        document_id="doc-a.md",
        graph={
            "nodes": [
                {"id": "doc_a", "label": "A.md", "type": "DOCUMENT", "sources": ["A.md"]},
                {"id": "fastapi", "label": "FastAPI", "type": "FRAMEWORK", "sources": ["A.md"]},
            ],
            "edges": [
                {
                    "source": "doc_a",
                    "target": "fastapi",
                    "type": "USES",
                    "weight": 1,
                    "confidence": 0.8,
                    "sources": ["A.md"],
                }
            ],
        },
    )

    graph = repo.load_graph("u1")

    assert {node["id"] for node in graph["nodes"]} == {"doc_a", "fastapi"}
    assert [(edge["source"], edge["target"], edge["type"]) for edge in graph["edges"]] == [
        ("doc_a", "fastapi", "USES")
    ]


def test_graph_repository_keeps_shared_nodes_until_all_sources_are_deleted():
    repo = _repo()
    shared_node = {"id": "python", "label": "Python", "type": "PROGRAMMING_LANGUAGE", "sources": ["docs"]}

    repo.replace_document_graph(
        user_id="u1",
        document_id="a.md",
        graph={"nodes": [shared_node], "edges": []},
    )
    repo.replace_document_graph(
        user_id="u1",
        document_id="b.md",
        graph={"nodes": [shared_node], "edges": []},
    )

    repo.delete_for_document("a.md", "u1")
    assert [node["id"] for node in repo.load_graph("u1")["nodes"]] == ["python"]

    repo.delete_for_document("b.md", "u1")
    assert repo.load_graph("u1")["nodes"] == []


def test_graph_repository_combines_relation_evidence_from_multiple_documents():
    repo = _repo()
    nodes = [
        {"id": "python", "label": "Python", "type": "PROGRAMMING_LANGUAGE"},
        {"id": "fastapi", "label": "FastAPI", "type": "FRAMEWORK"},
    ]

    for document_id in ("a.md", "b.md"):
        repo.replace_document_graph(
            user_id="u1",
            document_id=document_id,
            graph={
                "nodes": nodes,
                "edges": [{
                    "source": "fastapi",
                    "target": "python",
                    "type": "WRITTEN_IN",
                    "weight": 1,
                    "confidence": 0.8,
                    "sources": [document_id],
                }],
            },
        )

    edge = repo.load_graph("u1")["edges"][0]
    assert edge["weight"] == 2
    assert edge["sources"] == ["a.md", "b.md"]
