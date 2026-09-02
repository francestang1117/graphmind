"""Workspace ownership and project-boundary regression tests."""

import asyncio
from copy import deepcopy

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.endpoints import auth, graph as graph_endpoint, search as search_endpoint, workspaces
from app.core.database import Base
from app.services.document_repository import DocumentRepository
from app.services.graph_repository import GraphRepository
from app.services.qa_engine import QAEngine
from app.services.workspace_repository import WorkspaceRepository


def _session_factory():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def _user(user_id: str) -> auth.UserRecord:
    return auth.UserRecord(
        id=user_id,
        email=f"{user_id}@example.com",
        name=user_id,
        hashed_password="",
        created_at="2026-01-01T00:00:00+00:00",
    )


def _document(filename: str, workspace_id: str) -> dict:
    return {
        "filename": filename,
        "stored_filename": filename,
        "original_filename": "paper.pdf",
        "file_size": 42,
        "file_extension": ".pdf",
        "file_type": ".pdf",
        "file_hash": "same-paper-bytes",
        "mime_type": "application/pdf",
        "file_path": f"/tmp/{filename}",
        "user_id": "researcher",
        "workspace_id": workspace_id,
        "created_at": "2026-05-01T00:00:00+00:00",
        "modified_at": "2026-05-01T00:00:00+00:00",
    }


def test_workspace_routes_create_list_and_enforce_owner(monkeypatch):
    session_factory = _session_factory()
    repository = WorkspaceRepository(session_factory=session_factory, enabled=lambda: True)
    monkeypatch.setattr(workspaces, "workspace_repository", repository)

    owner = _user("researcher")
    other_user = _user("other")

    created = asyncio.run(
        workspaces.create_workspace(
            workspaces.WorkspaceCreate(
                name="Diabetes outcomes",
                research_question="Which interventions improve HbA1c?",
            ),
            owner,
        )
    )
    listed = asyncio.run(workspaces.list_workspaces(owner))
    fetched = asyncio.run(workspaces.get_workspace(created.id, owner))

    assert fetched.id == created.id
    assert fetched.research_question == "Which interventions improve HbA1c?"
    assert any(item.id == created.id for item in listed)

    with pytest.raises(workspaces.HTTPException) as exc:
        asyncio.run(workspaces.get_workspace(created.id, other_user))
    assert exc.value.status_code == 404


def test_same_paper_can_live_in_two_workspaces_without_crossing_reads():
    session_factory = _session_factory()
    workspace_repo = WorkspaceRepository(session_factory=session_factory, enabled=lambda: True)
    document_repo = DocumentRepository(session_factory=session_factory, enabled=lambda: True)

    first = workspace_repo.create("researcher", "First project", "Question one")
    second = workspace_repo.create("researcher", "Second project", "Question two")
    first_document = _document("first-paper.pdf", first["id"])
    second_document = deepcopy(first_document)
    second_document["filename"] = "second-paper.pdf"
    second_document["stored_filename"] = "second-paper.pdf"
    second_document["file_path"] = "/tmp/second-paper.pdf"
    second_document["workspace_id"] = second["id"]

    document_repo.save_metadata(first_document)
    document_repo.save_metadata(second_document)

    assert document_repo.list("researcher", first["id"])[0]["filename"] == "first-paper.pdf"
    assert document_repo.list("researcher", second["id"])[0]["filename"] == "second-paper.pdf"
    assert document_repo.get("second-paper.pdf", "researcher", first["id"]) is None


def test_graph_reads_are_scoped_to_workspace():
    session_factory = _session_factory()
    workspace_repo = WorkspaceRepository(session_factory=session_factory, enabled=lambda: True)
    graph_repo = GraphRepository(session_factory=session_factory, enabled=lambda: True)
    document_repo = DocumentRepository(session_factory=session_factory, enabled=lambda: True)

    first = workspace_repo.create("researcher", "First project")
    second = workspace_repo.create("researcher", "Second project")
    first_document = _document("first-paper.pdf", first["id"])
    second_document = deepcopy(first_document)
    second_document["filename"] = "second-paper.pdf"
    second_document["stored_filename"] = "second-paper.pdf"
    second_document["file_path"] = "/tmp/second-paper.pdf"
    second_document["workspace_id"] = second["id"]
    document_repo.save_metadata(first_document)
    document_repo.save_metadata(second_document)

    graph_repo.replace_document_graph(
        user_id="researcher",
        workspace_id=first["id"],
        document_id=first_document["document_id"],
        graph={"nodes": [{"id": "human-trial", "label": "Human trial", "type": "CONCEPT"}], "edges": []},
    )
    graph_repo.replace_document_graph(
        user_id="researcher",
        workspace_id=second["id"],
        document_id=second_document["document_id"],
        graph={"nodes": [{"id": "animal-model", "label": "Animal model", "type": "CONCEPT"}], "edges": []},
    )

    first_nodes = {node["id"] for node in graph_repo.load_graph("researcher", first["id"])["nodes"]}
    second_nodes = {node["id"] for node in graph_repo.load_graph("researcher", second["id"])["nodes"]}

    assert first_nodes == {"human-trial"}
    assert second_nodes == {"animal-model"}


def test_search_index_only_contains_the_selected_workspace(monkeypatch):
    session_factory = _session_factory()
    workspace_repo = WorkspaceRepository(session_factory=session_factory, enabled=lambda: True)
    first = workspace_repo.create("researcher", "First project")
    second = workspace_repo.create("researcher", "Second project")

    documents = {
        first["id"]: [{
            "filename": "first.md",
            "original_filename": "First paper.md",
            "file_path": "/tmp/first.md",
        }],
        second["id"]: [{
            "filename": "second.md",
            "original_filename": "Second paper.md",
            "file_path": "/tmp/second.md",
        }],
    }
    parsed = {
        ("first.md", first["id"]): {"chunks": [{"text": "Human trial results", "type": "section"}]},
        ("second.md", second["id"]): {"chunks": [{"text": "Animal model results", "type": "section"}]},
    }

    class FakeDocumentService:
        def list_documents(self, user_id, workspace_id=None):
            return documents.get(workspace_id, [])

    monkeypatch.setattr(search_endpoint, "document_service", FakeDocumentService())
    monkeypatch.setattr(
        search_endpoint,
        "get_cached_parse",
        lambda filename, user_id, workspace_id=None: parsed[(filename, workspace_id)],
    )

    store = search_endpoint.rebuild_vector_index("researcher", first["id"])
    indexed_text = " ".join(chunk.text for chunk in store.chunks.values())

    assert {chunk.document for chunk in store.chunks.values()} == {"First paper.md"}
    assert "Human trial results" in indexed_text
    assert "Animal model results" not in indexed_text


def test_qa_passes_workspace_to_vector_and_graph_reads(monkeypatch):
    seen = {}

    class FakeStore:
        def get_context_for_qa(self, question, n_chunks=5):
            return "[From: first.md | Relevance: 80.0%]\nHuman trial results"

    class FakeGraph:
        def search_nodes(self, question, limit=5):
            return []

    def rebuild_vector_index(user_id=None, workspace_id=None):
        seen["search"] = (user_id, workspace_id)
        return FakeStore()

    def rebuild_graph_from_documents(user_id=None, workspace_id=None):
        seen["graph"] = (user_id, workspace_id)
        return FakeGraph()

    monkeypatch.setattr(search_endpoint, "rebuild_vector_index", rebuild_vector_index)
    monkeypatch.setattr(graph_endpoint, "rebuild_graph_from_documents", rebuild_graph_from_documents)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)

    result = QAEngine().answer(
        "What happened in the trial?",
        user_id="researcher",
        workspace_id="workspace-a",
    )

    assert seen == {
        "search": ("researcher", "workspace-a"),
        "graph": ("researcher", "workspace-a"),
    }
    assert "Human trial results" in result["answer"]
