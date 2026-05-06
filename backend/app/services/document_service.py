"""Upload workflow shared by the document API routes."""

from typing import Any, Optional

from app.core.config import settings
from app.core.database import db_enabled
from app.services.document_repository import DocumentRepository, document_repository
from app.services.file_storage import FileStorage, file_storage
from app.services.persistence_service import mark_document_deleted, save_document_record
from app.services.virus_scanner import VirusScanner, virus_scanner
from app.utils.file_validator import FileValidator
from app.utils.file_validator import UploadValidationError


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
        metadata = self.storage.save_file(content, safe_name, mime_type, user_id=user_id)
        if self._db_available():
            self.repository.save_metadata(metadata)
        else:
            save_document_record(metadata)
        return metadata

    def list_documents(self, user_id: Optional[str] = None) -> list[dict[str, Any]]:
        if self._db_available():
            records = self.repository.list(user_id)
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
        deleted = self.storage.delete_file(filename, user_id)
        if deleted and user_id:
            if self._db_available():
                self.repository.mark_deleted(filename, user_id)
            else:
                mark_document_deleted(filename, user_id)
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

        # If fail-open is off, scanner outages land here too.
        if result.threat:
            raise UploadValidationError(f"Malware detected: {result.threat}")

        raise UploadValidationError(
            "Virus scanner is unavailable. Upload was blocked for safety."
        )


document_service = DocumentService()
