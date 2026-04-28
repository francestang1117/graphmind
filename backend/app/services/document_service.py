"""Document upload workflow.

This service keeps the API route small: validate bytes, store the file, and
shape responses for the current frontend.

Implemented:
- upload validation orchestration
- storage handoff
- document list/detail/delete facade
"""

from typing import Any, Optional

from app.services.file_storage import FileStorage, file_storage
from app.utils.file_validator import FileValidator


class DocumentService:
    def __init__(
        self,
        storage: FileStorage = file_storage,
        validator: Optional[FileValidator] = None,
    ) -> None:
        self.storage = storage
        self.validator = validator or FileValidator()

    def save_upload(self, filename: str, content: bytes) -> dict[str, Any]:
        safe_name, mime_type = self.validator.validate(filename or "upload", content)
        return self.storage.save_file(content, safe_name, mime_type)

    def list_documents(self) -> list[dict[str, Any]]:
        return self.storage.list_files()

    def get_document(self, filename: str) -> Optional[dict[str, Any]]:
        return self.storage.get_file_info(filename)

    def delete_document(self, filename: str) -> bool:
        return self.storage.delete_file(filename)


document_service = DocumentService()
