"""Upload workflow shared by the document API routes."""

import logging
from typing import Any, Optional

from app.core.config import settings
from app.core.database import db_enabled
from app.core.errors import (
    DuplicateUploadError,
    MalwareDetectedError,
    StorageOperationError,
    VirusScannerUnavailableError,
)
from app.services.document_repository import DocumentRepository, document_repository
from app.services.file_storage import DuplicateFileError, FileStorage, FileStorageError, file_storage
from app.services.persistence_service import mark_document_deleted, save_document_record
from app.services.virus_scanner import VirusScanner, virus_scanner
from app.utils.file_validator import FileValidator

log = logging.getLogger(__name__)


class DocumentService:
    def __init__(
        self,
        storage: FileStorage = file_storage,
        validator: Optional[FileValidator] = None,
        scanner: Optional[VirusScanner] = virus_scanner,
        repository: Optional[DocumentRepository] = document_repository,
        use_database: Optional[bool] = None,
        virus_scan_enabled: Optional[bool] = None,
    ) -> None:
        self.storage = storage
        self.validator = validator or FileValidator()
        self.scanner = scanner
        self.repository = repository
        self.virus_scan_enabled = settings.VIRUS_SCAN_ENABLED if virus_scan_enabled is None else virus_scan_enabled
        # Temp storage in tests should not write into the local graphmind.db.
        self.use_database = (storage is file_storage and db_enabled()) if use_database is None else use_database

    def save_upload(self, filename: str, content: bytes, user_id: str = "local-dev") -> dict[str, Any]:
        safe_name, mime_type = self.validator.validate(filename or "upload", content)
        # Scan before save_file so unchecked bytes never touch storage.
        self._scan_for_malware(content)

        try:
            metadata = self.storage.save_file(content, safe_name, mime_type, user_id=user_id)
        except DuplicateFileError as exc:
            # Storage knows the duplicate by hash; the API only needs a stable
            # conflict shape it can turn into a nice "already uploaded" row.
            existing = exc.metadata
            raise DuplicateUploadError(
                details={
                    "existing_filename": existing.get("filename", ""),
                    "original_filename": existing.get("original_filename", ""),
                    "file_hash": existing.get("file_hash", ""),
                },
            ) from exc
        except FileStorageError as exc:
            log.warning("Could not store uploaded file %s: %s", safe_name, exc)
            raise StorageOperationError(details={"filename": safe_name}) from exc

        if self._db_available():
            self.repository.save_metadata(metadata)
        else:
            # During early local work the sidecar path keeps uploads usable even
            # when the database layer is not installed or intentionally off.
            save_document_record(metadata)
        return metadata

    def list_documents(self, user_id: Optional[str] = None) -> list[dict[str, Any]]:
        if self._db_available():
            records = self.repository.list(user_id)
            # If the DB has ever seen this user, it is the source of truth.
            # That keeps soft-deleted rows from reappearing through sidecars.
            if records or self.repository.has_any(user_id):
                return records
        return self.storage.list_files(user_id)

    def get_document(self, filename: str, user_id: Optional[str] = None) -> Optional[dict[str, Any]]:
        if self._db_available():
            record = self.repository.get(filename, user_id)
            if record or self.repository.has_record(filename, user_id):
                return record
        return self.storage.get_file_info(filename, user_id)

    def delete_document(self, filename: str, user_id: Optional[str] = None) -> bool:
        try:
            deleted = self.storage.delete_file(filename, user_id)
        except FileStorageError as exc:
            log.warning("Could not delete stored file %s: %s", filename, exc)
            raise StorageOperationError(details={"filename": filename}) from exc

        if deleted and user_id:
            if self._db_available():
                self.repository.mark_deleted(filename, user_id)
            else:
                mark_document_deleted(filename, user_id)
            from app.services.parsed_artifact_repository import parsed_artifact_repository

            parsed_artifact_repository.delete_for_document(filename)
        return deleted

    def _db_available(self) -> bool:
        return bool(self.use_database and self.repository and self.repository.available())

    def _scan_for_malware(self, content: bytes) -> None:
        """Run ClamAV before writing bytes to disk when scanning is enabled."""
        if not self.virus_scan_enabled or not self.scanner:
            return

        result = self.scanner.scan(content)
        if result.clean:
            return

        if result.threat:
            # Threats and scanner outages are different user stories: one is a
            # bad file, the other is an infrastructure problem.
            raise MalwareDetectedError(
                f"Malware detected: {result.threat}",
                details={"threat": result.threat, "scanner": result.source},
            )

        raise VirusScannerUnavailableError(
            "Virus scanner is unavailable. Upload was blocked for safety.",
            details={"scanner": result.source, "error": result.error or ""},
        )


document_service = DocumentService()
