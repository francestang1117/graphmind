"""Endpoint-level checks for the current document upload workflow."""

import asyncio
from io import BytesIO
from pathlib import Path

from fastapi import BackgroundTasks, UploadFile
import pytest

from app.api.endpoints import documents
from app.services.document_service import DocumentService
from app.services.file_storage import FileStorage


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def temp_document_service(tmp_path, monkeypatch):
    service = DocumentService(storage=FileStorage(tmp_path))
    monkeypatch.setattr(documents, "document_service", service)
    return service


def make_upload(filename, content):
    return UploadFile(filename=filename, file=BytesIO(content))


def test_upload_returns_stored_file_metadata(temp_document_service):
    response = run(
        documents.upload_document(
            BackgroundTasks(),
            make_upload("notes.md", b"# Notes\n\nUseful text."),
        )
    )

    assert response.original_filename == "notes.md"
    assert response.status == "uploaded"
    assert response.file_type == ".md"


def test_list_get_and_delete_document(temp_document_service):
    uploaded = run(
        documents.upload_document(
            BackgroundTasks(),
            make_upload("keep.txt", b"plain text"),
        )
    )

    listed = run(documents.list_documents())
    fetched = run(documents.get_document(uploaded.filename))
    deleted = run(documents.delete_document(uploaded.filename))

    assert listed.total == 1
    assert fetched.original_filename == "keep.txt"
    assert deleted == {"message": "File deleted"}


def test_open_document_returns_original_file(temp_document_service):
    uploaded = run(
        documents.upload_document(
            BackgroundTasks(),
            make_upload("keep.txt", b"plain text"),
        )
    )

    response = run(documents.open_document(uploaded.filename))

    assert response.media_type == "text/plain"
    assert response.filename == "keep.txt"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-security-policy"] == "sandbox"
    assert response.headers["content-disposition"].startswith("inline")
    assert Path(response.path).read_bytes() == b"plain text"


def test_open_risky_document_downloads_instead_of_inline(temp_document_service):
    uploaded = run(
        documents.upload_document(
            BackgroundTasks(),
            make_upload("page.html", b"<!doctype html><script>alert(1)</script>"),
        )
    )

    response = run(documents.open_document(uploaded.filename))

    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-disposition"].startswith("attachment")


def test_open_missing_document_raises_not_found(temp_document_service):
    with pytest.raises(documents.HTTPException) as exc:
        run(documents.open_document("missing.txt"))

    assert exc.value.status_code == 404


def test_parsed_document_persists_chunks_and_entities(temp_document_service, monkeypatch):
    saved = {}

    class FakeArtifactRepository:
        def replace_for_document(self, filename, parsed, entities):
            saved["filename"] = filename
            saved["chunks"] = parsed.get("chunks", [])
            saved["entities"] = entities

        def delete_for_document(self, filename):
            saved["deleted"] = filename

    monkeypatch.setattr(
        "app.api.endpoints.documents_with_markdown.parsed_artifact_repository",
        FakeArtifactRepository(),
    )

    uploaded = run(
        documents.upload_document(
            BackgroundTasks(),
            make_upload("notes.md", b"# Notes\n\nGraphMind uses FastAPI and Python."),
        )
    )

    parsed = run(documents.get_parsed_document(uploaded.filename))

    assert parsed.chunks_count > 0
    assert saved["filename"] == uploaded.filename
    assert saved["chunks"]
    assert any(getattr(entity, "text", "") == "FastAPI" for entity in saved["entities"])


def test_invalid_upload_raises_http_error(temp_document_service):
    with pytest.raises(documents.HTTPException) as exc:
        run(
            documents.upload_document(
                BackgroundTasks(),
                make_upload("bad.exe", b"MZ"),
            )
        )

    assert exc.value.status_code == 400
