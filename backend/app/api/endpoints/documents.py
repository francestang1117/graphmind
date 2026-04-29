"""Document upload and listing endpoints.

Implemented:
- single-file upload API
- validation and storage handoff
- background parser queueing with cached summaries
- parsed structure lookup for all supported document types
- document list, detail, and delete endpoints
"""

from typing import List

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, UploadFile
from pydantic import BaseModel

from app.api.endpoints.documents_with_markdown import (
    clear_cached_parse,
    document_summary,
    get_cached_parse,
    parse_document_file,
)
from app.services.document_service import document_service
from app.services.file_storage import DuplicateFileError
from app.utils.file_validator import UploadValidationError


router = APIRouter()


class UploadResponse(BaseModel):
    filename: str
    original_filename: str
    file_size: int
    file_type: str
    file_hash: str
    status: str = "uploaded"


class DuplicateResponse(BaseModel):
    detail: str
    existing_filename: str
    original_filename: str
    file_hash: str


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


class ParsedDocumentSummary(BaseModel):
    filename: str
    title: str
    format: str
    headers_count: int
    sections_count: int
    chunks_count: int
    links_count: int
    images_count: int
    list_items_count: int
    code_blocks_count: int
    tables_count: int
    imports_count: int
    functions_count: int
    classes_count: int
    entities_count: int
    pages_count: int
    paragraphs_count: int
    comments_count: int
    inherited_styles_count: int
    word_count: int
    reading_time: int
    has_code: bool
    languages: List[str]
    imports: List[str]
    functions: List[str]
    classes: List[str]
    entities: List[dict]


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
    except DuplicateFileError as exc:
        existing = exc.metadata
        raise HTTPException(
            status_code=409,
            detail={
                "message": "This file has already been uploaded.",
                "existing_filename": existing["filename"],
                "original_filename": existing["original_filename"],
                "file_hash": existing["file_hash"],
            },
        ) from exc

    background_tasks.add_task(
        parse_document_file,
        metadata["stored_filename"],
        metadata["file_path"],
        metadata["original_filename"],
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


@router.get("/{filename}/parsed", response_model=ParsedDocumentSummary)
async def get_parsed_document(filename: str) -> ParsedDocumentSummary:
    """Return the cached parse summary for a stored file."""
    metadata = document_service.get_document(filename)
    if not metadata:
        raise HTTPException(status_code=404, detail="File not found")

    parsed = get_cached_parse(filename)
    if not parsed:
        try:
            parsed = parse_document_file(
                filename,
                metadata["file_path"],
                metadata["original_filename"],
            )
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"Parse failed: {exc}") from exc
    elif metadata["file_extension"] == ".docx":
        parsed = parse_document_file(
            filename,
            metadata["file_path"],
            metadata["original_filename"],
        )
    return ParsedDocumentSummary(
        **document_summary(filename, parsed, metadata["original_filename"])
    )


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
