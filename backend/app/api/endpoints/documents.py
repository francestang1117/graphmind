import logging
import uuid
from pathlib import Path
from typing import List

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Request, Response, UploadFile
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
from app.core.config import settings
from app.core.errors import (
    ParseError,
    ProcessingQueueError,
    StorageAccessError,
    StoredFileMissingError,
    UploadRejectedError,
)
from app.core.metrics import record_upload
from app.core.rate_limit import upload_limit
from app.services.job_repository import job_repository
from app.services.pipeline import process_uploaded_document
from app.tasks.process_document import process_document
from app.utils.file_validator import UploadValidationError


router = APIRouter()
log = logging.getLogger(__name__)

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
    job_id: str | None = None


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
    response: Response = None,
) -> UploadResponse:
    """Validate, store, and queue a document for parsing.

    `request` is only here because slowapi needs it for the rate-limit key.
    """
    content = await file.read()

    try:
        metadata = document_service.save_upload(file.filename or "upload", content, user_id=_user_id(user))
    except UploadValidationError as exc:
        # Keep upload failures machine-readable for the UI; raw exception text
        # alone is hard to branch on.
        record_upload("rejected", file.filename or "upload", len(content))
        raise UploadRejectedError(str(exc)) from exc

    record_upload("accepted", metadata["original_filename"], metadata["file_size"])
    job_id = _queue_processing(background_tasks, metadata, _user_id(user))

    return UploadResponse(
        filename=metadata["stored_filename"],
        original_filename=metadata["original_filename"],
        file_size=metadata["file_size"],
        file_type=metadata["file_type"],
        file_hash=metadata["file_hash"],
        job_id=job_id,
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

    user_id = _user_id(user)
    parsed = get_cached_parse(filename, user_id)
    if not parsed:
        try:
            parsed = parse_document_file(
                filename,
                metadata["file_path"],
                metadata["original_filename"],
                user_id=user_id,
                document_id=metadata.get("document_id", ""),
            )
        except Exception as exc:
            # Parsing can fail for format-specific reasons. Expose a stable
            # code, but keep the original reason in details for debugging.
            raise ParseError(
                details={
                    "filename": filename,
                    "original_filename": metadata.get("original_filename", ""),
                    "reason": str(exc),
                }
            ) from exc
    elif metadata["file_extension"] == ".docx":
        parsed = parse_document_file(
            filename,
            metadata["file_path"],
            metadata["original_filename"],
            user_id=user_id,
            document_id=metadata.get("document_id", ""),
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

    try:
        file_path = document_service.storage.ensure_local_file(metadata)
    except FileNotFoundError:
        raise StoredFileMissingError(details={"filename": filename})
    except Exception as exc:
        raise StorageAccessError(details={"filename": filename, "reason": str(exc)}) from exc

    allowed_roots = {
        Path(settings.UPLOAD_DIR).resolve(),
        Path(getattr(document_service.storage, "root", settings.UPLOAD_DIR)).resolve(),
    }
    resolved_path = file_path.resolve()
    if not any(_is_within(resolved_path, root) for root in allowed_roots):
        # Metadata should never point outside upload storage. If it does, block
        # before FileResponse has a chance to touch the path.
        raise StorageAccessError(details={"filename": filename})

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


def _queue_processing(background_tasks: BackgroundTasks, metadata: dict, user_id: str) -> str | None:
    if settings.CELERY_ENABLED:
        document_id = metadata.get("document_id") or metadata["stored_filename"]
        # Put the row in the database before the broker can wake a worker up.
        # Otherwise a fast worker can write SUCCESS and then lose it to the
        # route's late PENDING insert.
        job_id = uuid.uuid4().hex
        job_repository.create(
            job_id,
            user_id=user_id,
            document_id=document_id,
            original_filename=metadata["original_filename"],
        )

        try:
            process_document.apply_async(
                args=(
                    metadata["file_path"],
                    document_id,
                    metadata["original_filename"],
                    user_id,
                    metadata["stored_filename"],
                ),
                task_id=job_id,
            )
        except Exception as exc:
            failure_message = "Could not queue document processing."
            log.exception("Could not publish processing job %s", job_id)
            try:
                job_repository.upsert(
                    job_id,
                    user_id=user_id,
                    document_id=document_id,
                    original_filename=metadata["original_filename"],
                    status="FAILURE",
                    step="Queue failed",
                    progress=0,
                    error=failure_message,
                )
            except Exception:
                log.exception("Could not record failed processing job %s", job_id)
            raise ProcessingQueueError(details={"job_id": job_id}) from exc
        return job_id

    background_tasks.add_task(
        process_uploaded_document,
        metadata["stored_filename"],
        metadata["file_path"],
        metadata["original_filename"],
        user_id,
        metadata.get("document_id", ""),
    )
    return None


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
    clear_cached_parse(filename, _user_id(user))
    return {"message": "File deleted"}
