"""Endpoint-level checks for the current document upload workflow."""

import asyncio
from io import BytesIO

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


def test_invalid_upload_raises_http_error(temp_document_service):
    with pytest.raises(documents.HTTPException) as exc:
        run(
            documents.upload_document(
                BackgroundTasks(),
                make_upload("bad.exe", b"MZ"),
            )
        )

    assert exc.value.status_code == 400
