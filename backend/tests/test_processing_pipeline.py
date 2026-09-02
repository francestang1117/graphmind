"""Processing pipeline tests for the upload-to-search path."""

import pytest

from app.services.entity_extractor import EntityExtractor
from app.services.graph_builder_enhanced import KnowledgeGraph
from app.services.pipeline import ProcessingCancelledError, ProcessingPipeline
from app.services.vector_store import VectorStore
from app.tasks import process_document as task_module


def test_processing_pipeline_updates_graph_and_search_index(tmp_path):
    file_path = tmp_path / "rag.md"
    file_path.write_text(
        "# RAG System\n\nFastAPI uses Python for semantic search and a knowledge graph.",
        encoding="utf-8",
    )
    graph = KnowledgeGraph()
    store = VectorStore()
    progress = []
    persisted = []

    result = ProcessingPipeline(
        extractor=EntityExtractor(model_name=None),
        graph=graph,
        store=store,
        graph_repo=FakeGraphRepository(persisted),
    ).process(
        str(file_path),
        "hash.md",
        "RAG System.md",
        on_progress=lambda step, pct: progress.append((step, pct)),
    )

    assert result["status"] == "indexed"
    assert result["chunks_count"] >= 1
    assert result["entities_count"] >= 3
    assert result["indexed_chunks"] >= 1
    assert graph.get_stats()["total_nodes"] >= 4
    assert store.hybrid_search("semantic search", 3)
    assert persisted[0]["document_id"] == "hash.md"
    assert persisted[0]["graph"]["nodes"]
    assert progress[0] == ("Parsing document", 15)
    assert progress[-1] == ("Done", 100)


def test_processing_pipeline_stops_before_writing_when_document_is_deleted(tmp_path):
    file_path = tmp_path / "deleted.md"
    file_path.write_text("# Deleted\n\nFastAPI uses Python.", encoding="utf-8")
    graph = KnowledgeGraph()
    store = VectorStore()

    with pytest.raises(ProcessingCancelledError):
        ProcessingPipeline(
            extractor=EntityExtractor(model_name=None),
            graph=graph,
            store=store,
            graph_repo=FakeGraphRepository([]),
        ).process(
            str(file_path),
            "deleted.md",
            should_cancel=lambda: True,
        )

    assert graph.get_stats()["total_nodes"] == 0
    assert store.chunks == {}


class FakeGraphRepository:
    def __init__(self, calls):
        self.calls = calls

    def replace_document_graph(self, **kwargs):
        self.calls.append(kwargs)


class FakeTask:
    def __init__(self):
        self.updates = []

    def update_state(self, state, meta):
        self.updates.append((state, meta))


class FakeDocumentService:
    def __init__(self, documents):
        self.documents = documents

    def get_document(self, filename, user_id=None):
        return next((item for item in self.documents if item["filename"] == filename), None)

    def list_documents(self, user_id=None):
        return list(self.documents)


class FakePipeline:
    def __init__(self, fail_for=None):
        self.calls = []
        self.fail_for = set(fail_for or [])

    def process(
        self,
        file_path,
        filename,
        original_filename="",
        user_id="local-dev",
        on_progress=None,
        document_id=None,
        should_cancel=None,
    ):
        self.calls.append((file_path, filename, original_filename))
        if should_cancel and should_cancel():
            raise ProcessingCancelledError("Document was deleted while reindexing")
        if filename in self.fail_for:
            raise RuntimeError("parse failed")
        if on_progress:
            on_progress("Done", 100)
        return {"filename": filename, "status": "indexed"}


def test_reindex_document_uses_stored_metadata(monkeypatch):
    docs = [
        {
            "filename": "hash.md",
            "file_path": "/tmp/hash.md",
            "original_filename": "notes.md",
        }
    ]
    fake_pipeline = FakePipeline()
    monkeypatch.setattr(task_module, "document_service", FakeDocumentService(docs))
    monkeypatch.setattr(task_module, "pipeline", fake_pipeline)

    result = task_module.reindex_document.run("hash.md")

    assert result == {"filename": "hash.md", "status": "indexed"}
    assert fake_pipeline.calls == [("/tmp/hash.md", "hash.md", "notes.md")]


def test_reindex_document_stops_when_its_job_is_revoked(monkeypatch):
    docs = [
        {
            "filename": "hash.md",
            "file_path": "/tmp/hash.md",
            "original_filename": "notes.md",
        }
    ]
    fake_pipeline = FakePipeline()
    monkeypatch.setattr(task_module, "document_service", FakeDocumentService(docs))
    monkeypatch.setattr(task_module, "pipeline", fake_pipeline)
    monkeypatch.setattr(task_module, "_job_was_revoked", lambda task, user_id: True)

    result = task_module.reindex_document.run("hash.md")

    assert result["status"] == "cancelled"
    assert fake_pipeline.calls == [("/tmp/hash.md", "hash.md", "notes.md")]


def test_reindex_all_documents_continues_after_one_failure(monkeypatch):
    docs = [
        {"filename": "ok.md", "file_path": "/tmp/ok.md", "original_filename": "ok.md"},
        {"filename": "bad.md", "file_path": "/tmp/bad.md", "original_filename": "bad.md"},
    ]
    fake_pipeline = FakePipeline(fail_for={"bad.md"})
    monkeypatch.setattr(task_module, "document_service", FakeDocumentService(docs))
    monkeypatch.setattr(task_module, "pipeline", fake_pipeline)

    result = task_module.reindex_all_documents.run()

    assert result["status"] == "completed_with_errors"
    assert result["total"] == 2
    assert result["reindexed"] == 1
    assert result["failed"] == 1
    assert result["failures"][0]["filename"] == "bad.md"
