"""Small application error types shared by API routes.

FastAPI's default errors are fine for validation/auth cases, but product
workflows need stable codes so the frontend can show better messages without
matching English text.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

log = logging.getLogger(__name__)


class AppError(Exception):
    """Base error for failures we expect and can explain to the client."""

    status_code = 500
    code = "internal_error"
    message = "Something went wrong."

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        status_code: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.message = message or self.message
        self.code = code or self.code
        self.status_code = status_code or self.status_code
        self.details = details or {}
        super().__init__(self.message)


class UploadRejectedError(AppError):
    status_code = 400
    code = "upload_validation_failed"
    message = "Upload validation failed."


class DuplicateUploadError(AppError):
    status_code = 409
    code = "duplicate_file"
    message = "This file has already been uploaded."


class ParseError(AppError):
    status_code = 422
    code = "parse_failed"
    message = "Could not parse this file."


class StorageAccessError(AppError):
    status_code = 403
    code = "stored_file_path_invalid"
    message = "Stored file path is invalid."


class StoredFileMissingError(AppError):
    status_code = 404
    code = "stored_file_missing"
    message = "Stored file is missing."


class StorageOperationError(AppError):
    status_code = 500
    code = "storage_operation_failed"
    message = "File storage operation failed."


class DatabaseOperationError(AppError):
    status_code = 503
    code = "database_operation_failed"
    message = "Database operation failed."


class MalwareDetectedError(AppError):
    status_code = 400
    code = "malware_detected"
    message = "Malware was detected in the uploaded file."


class VirusScannerUnavailableError(AppError):
    status_code = 503
    code = "virus_scanner_unavailable"
    message = "Virus scanner is unavailable."


def error_payload(error: AppError) -> dict[str, Any]:
    """Return the flat error shape used by GraphMind API errors."""
    payload: dict[str, Any] = {
        "detail": error.message,
        "code": error.code,
    }
    if error.details:
        payload["details"] = error.details
    return payload


def register_error_handlers(app: FastAPI) -> None:
    """Install handlers for errors raised by GraphMind services/routes."""

    @app.exception_handler(AppError)
    async def handle_app_error(_request: Request, exc: AppError) -> JSONResponse:
        # Expected 4xx errors are part of normal user flow; 5xx AppErrors mean
        # we kept control of the response but still need a server-side breadcrumb.
        if exc.status_code >= 500:
            log.error("%s: %s", exc.code, exc.message)
        return JSONResponse(status_code=exc.status_code, content=error_payload(exc))
