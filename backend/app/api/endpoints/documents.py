"""Routes for upload, file lookup, parsing summary, and delete."""

from pathlib import Path
from typing import List

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.api.endpoints.auth import UserRecord, current_user_or_dev
from app.api.endpoints.documents_with_markdown import (
    clear_cached_parse,
    document_summary,
    get_cached_parse,
    parse_document_file,
)
from app.services.document_service import document_service
from app.services.file_storage import DuplicateFileError
from app.core.config import settings
from app.core.rate_limit import upload_limit
from app.utils.file_validator import UploadValidationError


router = APIRouter()

INLINE_PREVIEW_EXTENSIONS = {".pdf", ".txt", ".md", ".json", ".csv"}
SAFE_FILE_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": "sandbox",
    "Cache-Control": "private, no-store",
}


def _user_id(user: UserRecord) -> str:
    """Direct tests pass the unresolved Depends object, so use local-dev there."""
    return getattr(user, "id", "local-dev")


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
@upload_limit
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    user: UserRecord = Depends(current_user_or_dev),
    request: Request = None,
) -> UploadResponse:
    """Validate, store, and queue a document for parsing.

    `request` is only here because slowapi needs it for the rate-limit key.
    """
    content = await file.read()

    try:
        metadata = document_service.save_upload(file.filename or "upload", content, user_id=_user_id(user))
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
async def list_documents(user: UserRecord = Depends(current_user_or_dev)) -> FileListResponse:
    """Return stored documents, newest first."""
    files = [FileInfo(**item) for item in document_service.list_documents(_user_id(user))]
    return FileListResponse(files=files, total=len(files))


@router.get("/{filename}/parsed", response_model=ParsedDocumentSummary)
async def get_parsed_document(
    filename: str,
    user: UserRecord = Depends(current_user_or_dev),
) -> ParsedDocumentSummary:
    """Return the cached parse summary for a stored file."""
    metadata = document_service.get_document(filename, _user_id(user))
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


@router.get("/{filename}/open")
async def open_document(
    filename: str,
    user: UserRecord = Depends(current_user_or_dev),
) -> FileResponse:
    """Serve the original file without letting risky formats execute inline."""
    metadata = document_service.get_document(filename, _user_id(user))
    if not metadata:
        raise HTTPException(status_code=404, detail="File not found")

    file_path = Path(metadata["file_path"])
    allowed_roots = {
        Path(settings.UPLOAD_DIR).resolve(),
        Path(getattr(document_service.storage, "root", settings.UPLOAD_DIR)).resolve(),
    }
    resolved_path = file_path.resolve()
    if not any(_is_within(resolved_path, root) for root in allowed_roots):
        raise HTTPException(status_code=403, detail="Stored file path is invalid")

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Stored file is missing")

    extension = metadata.get("file_extension", "").lower()
    # Browser preview is convenient, but inline HTML/code can execute in the
    # browser. Keep preview to passive formats and download everything else.
    disposition = "inline" if extension in INLINE_PREVIEW_EXTENSIONS else "attachment"

    return FileResponse(
        file_path,
        media_type=metadata.get("mime_type") or "application/octet-stream",
        filename=metadata.get("original_filename") or filename,
        content_disposition_type=disposition,
        headers=SAFE_FILE_HEADERS,
    )


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


@router.get("/{filename}", response_model=FileInfo)
async def get_document(
    filename: str,
    user: UserRecord = Depends(current_user_or_dev),
) -> FileInfo:
    """Return metadata for one stored document."""
    metadata = document_service.get_document(filename, _user_id(user))
    if not metadata:
        raise HTTPException(status_code=404, detail="File not found")
    return FileInfo(**metadata)


@router.delete("/{filename}")
async def delete_document(
    filename: str,
    user: UserRecord = Depends(current_user_or_dev),
) -> dict[str, str]:
    """Delete a stored document by its stored filename."""
    if not document_service.delete_document(filename, _user_id(user)):
        raise HTTPException(status_code=404, detail="File not found")
    clear_cached_parse(filename)
    return {"message": "File deleted"}
