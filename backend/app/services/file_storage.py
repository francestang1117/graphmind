"""Content-addressed local file storage.

Implemented:
- SHA-256 based filenames
- sidecar metadata JSON
- duplicate-content detection by hash
- list, lookup, load, and delete operations
- path guard before read/delete
"""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Union

from app.core.config import settings


class FileStorageError(IOError):
    """Raised when a storage operation fails unexpectedly."""


class DuplicateFileError(FileStorageError):
    """Raised when the same content has already been stored."""

    def __init__(self, metadata: dict[str, Any]) -> None:
        self.metadata = metadata
        super().__init__(
            f"Duplicate file content already exists as {metadata.get('original_filename')}"
        )


class FileStorage:
    """Store uploaded files by SHA-256 hash under a local root directory."""

    def __init__(self, root: Union[str, Path]) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def save_file(
        self,
        data: bytes,
        original_filename: str,
        mime_type: str = "application/octet-stream",
        user_id: str = "local-dev",
    ) -> dict[str, Any]:
        """Persist bytes atomically and return API-ready metadata."""
        extension = Path(original_filename).suffix.lower()
        file_hash = _sha256(data)
        dest = self._dest_path(file_hash, extension)
        dest.parent.mkdir(parents=True, exist_ok=True)

        # Deduplication is based on content, not filename. Renaming a file should
        # not create a second copy if the bytes are exactly the same.
        if dest.exists():
            existing = self.get_file_info(dest.name)
            if existing:
                raise DuplicateFileError(existing)

        tmp = dest.with_suffix(dest.suffix + ".tmp")
        try:
            tmp.write_bytes(data)
            tmp.rename(dest)
        except Exception as exc:
            tmp.unlink(missing_ok=True)
            raise FileStorageError(f"Failed to write {dest}: {exc}") from exc

        metadata = self._build_metadata(dest, original_filename, file_hash, mime_type, user_id)
        self._metadata_path(dest).write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return metadata

    def list_files(self, user_id: Optional[str] = None) -> list[dict[str, Any]]:
        """Return all stored file metadata, newest first."""
        files = []
        for metadata_path in self.root.glob("*/*.json"):
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if self._is_metadata_file(metadata_path, metadata) and self._belongs_to_user(metadata, user_id):
                files.append(metadata)
        return sorted(files, key=lambda item: item.get("created_at", ""), reverse=True)

    def get_file_info(self, filename: str, user_id: Optional[str] = None) -> Optional[dict[str, Any]]:
        """Return metadata for a stored filename."""
        safe_name = Path(filename).name
        for info in self.list_files(user_id):
            if info.get("filename") == safe_name:
                return info
        return None

    def delete_file(self, filename: str, user_id: Optional[str] = None) -> bool:
        """Delete a stored file and its sidecar metadata."""
        info = self.get_file_info(filename, user_id)
        if not info:
            return False

        path = Path(info["file_path"])
        if not self._is_under_root(path):
            raise FileStorageError(f"Refusing to delete path outside upload root: {path}")

        metadata_path = self._metadata_path(path)
        deleted = False
        for target in (path, metadata_path):
            try:
                target.unlink()
                deleted = True
            except FileNotFoundError:
                pass
            except OSError as exc:
                raise FileStorageError(f"Could not delete {target}: {exc}") from exc
        return deleted

    def load_file(self, filename: str, user_id: Optional[str] = None) -> bytes:
        """Read stored file bytes by stored filename."""
        info = self.get_file_info(filename, user_id)
        if not info:
            raise FileNotFoundError(filename)
        path = Path(info["file_path"])
        if not self._is_under_root(path):
            raise FileStorageError(f"Refusing to read path outside upload root: {path}")
        return path.read_bytes()

    def _dest_path(self, file_hash: str, extension: str) -> Path:
        ext = _normalise_ext(extension)
        prefix = file_hash[:2]
        return self.root / prefix / f"{file_hash}{ext}"

    def _metadata_path(self, path: Path) -> Path:
        return path.with_suffix(path.suffix + ".json")

    def _is_metadata_file(self, path: Path, metadata: dict[str, Any]) -> bool:
        """Distinguish sidecar metadata from uploaded .json documents."""
        # Uploaded JSON files live beside their metadata as:
        #   hash.json       -> user document
        #   hash.json.json  -> sidecar metadata
        # So list_files() must validate the schema instead of trusting '*.json'.
        required = {
            "filename",
            "stored_filename",
            "original_filename",
            "file_size",
            "file_extension",
            "file_path",
            "created_at",
        }
        if not required.issubset(metadata):
            return False
        stored_path = Path(str(metadata["file_path"]))
        return path == self._metadata_path(stored_path)

    def _build_metadata(
        self,
        path: Path,
        original_filename: str,
        file_hash: str,
        mime_type: str,
        user_id: str,
    ) -> dict[str, Any]:
        stat = path.stat()
        created_at = _to_iso(stat.st_ctime)
        modified_at = _to_iso(stat.st_mtime)
        return {
            "filename": path.name,
            "stored_filename": path.name,
            "original_filename": original_filename,
            "file_size": stat.st_size,
            "file_extension": path.suffix.lower(),
            "file_type": path.suffix.lower(),
            "file_hash": file_hash,
            "mime_type": mime_type,
            "file_path": str(path),
            "user_id": user_id,
            "created_at": created_at,
            "modified_at": modified_at,
        }

    def _belongs_to_user(self, metadata: dict[str, Any], user_id: Optional[str]) -> bool:
        """Older local files did not have user_id; keep them visible to local-dev."""
        if user_id is None:
            return True
        return metadata.get("user_id", "local-dev") == user_id

    def _is_under_root(self, path: Path) -> bool:
        try:
            path.resolve().relative_to(self.root.resolve())
            return True
        except ValueError:
            return False


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _normalise_ext(extension: str) -> str:
    if not extension:
        return ""
    return extension if extension.startswith(".") else f".{extension}"


def _to_iso(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()


file_storage = FileStorage(settings.UPLOAD_DIR)
