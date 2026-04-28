"""Document upload and listing endpoints.

Implemented:
- single-file upload API
- validation and storage handoff
- background parser queueing
- Markdown parse summary lookup
- document list, detail, and delete endpoints
"""

from typing import List

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, UploadFile
from pydantic import BaseModel

from app.api.endpoints.documents_with_markdown import (
    clear_cached_parse,
    get_cached_parse,
    markdown_summary,
    parse_markdown_bytes,
)
from app.services.document_service import document_service
from app.tasks.process_document import process_document
from app.utils.file_validator import UploadValidationError


router = APIRouter()


class UploadResponse(BaseModel):
    filename: str
    original_filename: str
    file_size: int
    file_type: str
    file_hash: str
    status: str = "uploaded"


class FileInfo(BaseModel):
    filename: str
    original_filename: str
    file_size: int
    file_extension: str
    file_type: str
    file_hash: str
    mime_type: str
    created_at: str
    modified_at: str


class FileListResponse(BaseModel):
    files: List[FileInfo]
    total: int


class ParsedMarkdownSummary(BaseModel):
    filename: str
    title: str
    headers_count: int
    sections_count: int
    links_count: int
    images_count: int
    code_blocks_count: int
    word_count: int
    reading_time: int
    has_code: bool
    languages: List[str]


@router.post("/upload", response_model=UploadResponse)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
) -> UploadResponse:
    """Validate, store, and queue a document for parsing."""
    content = await file.read()

    try:
        metadata = document_service.save_upload(file.filename or "upload", content)
    except UploadValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    background_tasks.add_task(
        process_document,
        metadata["file_path"],
        metadata["original_filename"],
    )
    if metadata["file_extension"] == ".md":
        background_tasks.add_task(
            parse_markdown_bytes,
            metadata["stored_filename"],
            content,
        )

    return UploadResponse(
        filename=metadata["stored_filename"],
        original_filename=metadata["original_filename"],
        file_size=metadata["file_size"],
        file_type=metadata["file_type"],
        file_hash=metadata["file_hash"],
    )


@router.get("/", response_model=FileListResponse)
async def list_documents() -> FileListResponse:
    """Return stored documents, newest first."""
    files = [FileInfo(**item) for item in document_service.list_documents()]
    return FileListResponse(files=files, total=len(files))


@router.get("/{filename}/parsed", response_model=ParsedMarkdownSummary)
async def get_parsed_document(filename: str) -> ParsedMarkdownSummary:
    """Return the cached Markdown parse summary for a stored file."""
    metadata = document_service.get_document(filename)
    if not metadata:
        raise HTTPException(status_code=404, detail="File not found")
    if metadata["file_extension"] != ".md":
        raise HTTPException(status_code=400, detail="Only Markdown files can be parsed")

    parsed = get_cached_parse(filename)
    if not parsed:
        raise HTTPException(status_code=404, detail="Parse result is not ready")
    return ParsedMarkdownSummary(**markdown_summary(filename, parsed))


@router.get("/{filename}", response_model=FileInfo)
async def get_document(filename: str) -> FileInfo:
    """Return metadata for one stored document."""
    metadata = document_service.get_document(filename)
    if not metadata:
        raise HTTPException(status_code=404, detail="File not found")
    return FileInfo(**metadata)


@router.delete("/{filename}")
async def delete_document(filename: str) -> dict[str, str]:
    """Delete a stored document by its stored filename."""
    if not document_service.delete_document(filename):
        raise HTTPException(status_code=404, detail="File not found")
    clear_cached_parse(filename)
    return {"message": "File deleted"}
