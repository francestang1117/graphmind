"""In-memory validation for uploaded documents.

Implemented:
- extension allow-list
- empty and oversized file rejection
- MIME detection with local fallback
- PDF/DOCX magic-byte checks
- basic text safety scan
- filename sanitization
"""

from pathlib import Path
import re
from typing import Tuple

try:
    import magic
except ImportError:
    magic = None

from app.core.config import get_settings

settings = get_settings()

class UploadValidationError(Exception):
    """Raised when an uploaded file fails validation."""

EXTENSION_MIME_MAP: dict[str, frozenset[str]] = {
    ".md": frozenset({"text/plain", "text/markdown", "text/x-markdown"}),
     ".txt":  frozenset({"text/plain"}),
    ".pdf":  frozenset({"application/pdf"}),
    ".docx": frozenset({
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/zip",
    }),
    ".py": frozenset({"text/plain", "text/x-python", "application/x-python", "text/x-script.python"}),
    ".js": frozenset({"text/plain", "text/javascript", "application/javascript", "text/ecmascript"}),
    ".ts": frozenset({"text/plain", "application/typescript", "text/typescript"}),
}

MAGIC_BYTES: dict[str, bytes] = {
    ".pdf":  b"%PDF",
    ".docx": b"PK\x03\x04",
}

_DANGER_PATTERNS: list[re.Pattern] = [
    re.compile(rb"<script[\s>]",             re.IGNORECASE),
    re.compile(rb"javascript\s*:",           re.IGNORECASE),
    re.compile(rb"vbscript\s*:",             re.IGNORECASE),
    re.compile(rb"on\w{2,20}\s*=\s*[\"']",  re.IGNORECASE),
    re.compile(rb"data\s*:\s*text/html",     re.IGNORECASE),
]

_TEXT_EXTENSIONS = frozenset({".md", ".txt", ".py", ".js", ".ts"})


class FileValidator:
    """Validate file type, size, MIME, signature, and basic text safety."""
    
    def validate(self, filename: str, data: bytes) -> Tuple[str, str]:
        """Return a safe filename and detected MIME type."""
        suffix = Path(filename).suffix.lower()

        self._check_extension(suffix)
        self._check_size(len(data))
        detected_mime = self._detect_mime(data)
        self._check_mime(suffix, detected_mime)
        self._check_magic_bytes(suffix, data)

        if suffix in _TEXT_EXTENSIONS:
            self._scan_content(data)

        return self._sanitise_filename(filename), detected_mime
    
    def _check_extension(self, suffix: str) -> None:
        """Reject extensions not present in the whitelist."""
        if suffix not in EXTENSION_MIME_MAP:
            allowed = ", ".join(sorted(EXTENSION_MIME_MAP.keys()))
            raise UploadValidationError(
                f"Extension '{suffix}' is not permitted. "
                f"Accepted: {allowed}"
            )
        
    def _check_size(self, size_bytes: int) -> None:
        """Reject empty files and files exceeding the configured cap."""
        if size_bytes == 0:
            raise UploadValidationError("The uploaded file is empty.")
        if size_bytes > settings.max_upload_bytes:
            size_mb = size_bytes / 1_048_576
            raise UploadValidationError(
                f"File is {size_mb:.1f} MB - exceeds the "
                f"{settings.MAX_UPLOAD_SIZE_MB} MB limit."
            )

    def _detect_mime(self, data: bytes) -> str:
        """Detect MIME type with libmagic, falling back to local signatures."""
        if magic is not None:
            try:
                mime = magic.from_buffer(data, mime=True)
                return mime or "application/octet-stream"
            except Exception:
                pass

        return self._fallback_detect_mime(data)

    def _fallback_detect_mime(self, data: bytes) -> str:
        """Small local fallback for development machines without libmagic."""
        if data.startswith(b"%PDF"):
            return "application/pdf"
        if data.startswith(b"PK\x03\x04"):
            return "application/zip"
        try:
            data.decode("utf-8")
            return "text/plain"
        except UnicodeDecodeError:
            return "application/octet-stream"
        
    def _check_mime(self, suffix: str, detected_mime: str) -> None:
        """Verify the detected MIME type is valid for the extension."""
        allowed = EXTENSION_MIME_MAP[suffix]
        if detected_mime not in allowed:
            raise UploadValidationError(
                f"Detected type '{detected_mime}' is not valid for '{suffix}'. "
                f"Expected one of: {sorted(allowed)}"
            )

    def _check_magic_bytes(self, suffix: str, data: bytes) -> None:
        """Verify binary formats start with their expected signature."""
        expected = MAGIC_BYTES.get(suffix)
        if expected is not None and not data.startswith(expected):
            raise UploadValidationError(
                f"File does not begin with the expected '{suffix}' signature. "
                "It may be corrupt or incorrectly named."
            )
        
    def _scan_content(self, data: bytes) -> None:
        """Scan the first 64 KB of text formats for dangerous patterns."""
        sample = data[:65_536]
        for pattern in _DANGER_PATTERNS:
            if pattern.search(sample):
                raise UploadValidationError(
                    "File contains dangerous embedded content (scripts, "
                    "event handlers, or data URIs) and was rejected."
                )

    @staticmethod
    def _sanitise_filename(filename: str) -> str:
        """Return a safe basename with dangerous filesystem characters removed."""
        name = Path(filename).name
        for ch in ('<', '>', ':', '"', '|', '?', '*', '\x00'):
            name = name.replace(ch, '_')
        stem = Path(name).stem[:200]
        ext = Path(name).suffix.lower()
        return f"{stem}{ext}" if stem else f"upload{ext}"
