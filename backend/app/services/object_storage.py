"""Optional S3/MinIO storage behind the same upload interface."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional, Union

from app.services.file_storage import FileStorage, FileStorageError

log = logging.getLogger(__name__)


class ObjectStorageError(FileStorageError):
    """Raised when the remote object store cannot finish an operation."""


class S3ObjectStorage(FileStorage):
    """Store uploads in S3/MinIO while keeping a local parser cache."""

    def __init__(
        self,
        root: Union[str, Path],
        bucket: str,
        endpoint_url: Optional[str] = None,
        access_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        region_name: str = "us-east-1",
        prefix: str = "uploads",
        force_path_style: bool = True,
        client: Any = None,
    ) -> None:
        super().__init__(root)
        if not bucket:
            raise ObjectStorageError("S3_BUCKET is required when STORAGE_BACKEND=s3")
        self.bucket = bucket
        self.prefix = prefix.strip("/")
        self.client = client or self._build_client(
            endpoint_url=endpoint_url,
            access_key=access_key,
            secret_key=secret_key,
            region_name=region_name,
            force_path_style=force_path_style,
        )

    def save_file(
        self,
        data: bytes,
        original_filename: str,
        mime_type: str = "application/octet-stream",
        user_id: str = "local-dev",
    ) -> dict[str, Any]:
        metadata = super().save_file(data, original_filename, mime_type, user_id=user_id)
        object_key = self.object_key(metadata)

        try:
            self.client.put_object(
                Bucket=self.bucket,
                Key=object_key,
                Body=data,
                ContentType=mime_type,
                Metadata={
                    "original-filename": original_filename,
                    "file-hash": metadata["file_hash"],
                    "user-id": user_id,
                },
            )
        except Exception as exc:
            # If the shared store rejected the write, keep the API honest and
            # remove the local cache that was created for the parser.
            super().delete_file(metadata["stored_filename"], user_id=user_id)
            raise ObjectStorageError(f"Could not upload {object_key} to object storage: {exc}") from exc

        metadata.update({
            "storage_backend": "s3",
            "bucket": self.bucket,
            "object_key": object_key,
        })
        self._write_metadata(metadata)
        return metadata

    def delete_file(self, filename: str, user_id: Optional[str] = None) -> bool:
        info = self.get_file_info(filename, user_id)
        if not info:
            return False

        object_key = self.object_key(info)
        try:
            self.client.delete_object(Bucket=self.bucket, Key=object_key)
        except Exception as exc:
            raise ObjectStorageError(f"Could not delete {object_key} from object storage: {exc}") from exc

        return super().delete_file(filename, user_id=user_id)

    def ensure_local_file(self, metadata: dict[str, Any]) -> Path:
        try:
            return super().ensure_local_file(metadata)
        except FileNotFoundError:
            pass

        path = Path(metadata["file_path"])
        if not self._is_under_root(path):
            raise FileStorageError(f"Refusing to restore path outside upload root: {path}")

        object_key = self.object_key(metadata)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.client.download_file(self.bucket, object_key, str(path))
        except Exception as exc:
            raise ObjectStorageError(f"Could not restore {object_key} from object storage: {exc}") from exc
        return path

    def presigned_download_url(self, metadata: dict[str, Any], expires_in: int = 300) -> str:
        """Return a short-lived direct download URL when the S3 client supports it."""
        object_key = self.object_key(metadata)
        try:
            return self.client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.bucket, "Key": object_key},
                ExpiresIn=expires_in,
            )
        except Exception as exc:
            raise ObjectStorageError(f"Could not sign download URL for {object_key}: {exc}") from exc

    def object_key(self, metadata: dict[str, Any]) -> str:
        existing = metadata.get("object_key")
        if existing:
            return str(existing)

        user_id = str(metadata.get("user_id") or "local-dev").strip("/") or "local-dev"
        filename = str(metadata.get("stored_filename") or metadata.get("filename"))
        parts = [part for part in (self.prefix, user_id, filename) if part]
        return "/".join(parts)

    def _write_metadata(self, metadata: dict[str, Any]) -> None:
        path = Path(metadata["file_path"])
        try:
            self._metadata_path(path).write_text(
                json.dumps(metadata, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as exc:
            raise ObjectStorageError(f"Could not update local object metadata: {exc}") from exc

    def _build_client(
        self,
        endpoint_url: Optional[str],
        access_key: Optional[str],
        secret_key: Optional[str],
        region_name: str,
        force_path_style: bool,
    ) -> Any:
        try:
            import boto3
            from botocore.config import Config
        except ImportError as exc:
            raise ObjectStorageError(
                "boto3 is required when STORAGE_BACKEND=s3. Install backend requirements first."
            ) from exc

        config = Config(s3={"addressing_style": "path" if force_path_style else "auto"})
        kwargs: dict[str, Any] = {
            "region_name": region_name,
            "config": config,
        }
        if endpoint_url:
            kwargs["endpoint_url"] = endpoint_url
        if access_key:
            kwargs["aws_access_key_id"] = access_key
        if secret_key:
            kwargs["aws_secret_access_key"] = secret_key
        return boto3.client("s3", **kwargs)
