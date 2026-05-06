"""Upload file checks before storage."""

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
    ".js": frozenset({
        "text/plain",
        "text/javascript",
        "application/javascript",
        "text/ecmascript",
        "application/json",
    }),
    ".ts": frozenset({
        "text/plain",
        "application/typescript",
        "text/typescript",
        "application/json",
        "text/x-c",
        "text/x-c++",
    }),
    ".json": frozenset({"application/json", "text/plain"}),
    ".csv": frozenset({"text/csv", "text/plain", "application/csv", "application/vnd.ms-excel"}),
    ".html": frozenset({"text/html", "text/plain"}),
    ".htm": frozenset({"text/html", "text/plain"}),
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

_HTML_DANGER_PATTERNS: list[re.Pattern] = [
    re.compile(rb"javascript\s*:",       re.IGNORECASE),
    re.compile(rb"vbscript\s*:",         re.IGNORECASE),
    re.compile(rb"data\s*:\s*text/html", re.IGNORECASE),
]

_TEXT_EXTENSIONS = frozenset({".md", ".txt", ".py", ".js", ".ts", ".json", ".csv", ".html", ".htm"})


class FileValidator:
    """Validate file type, size, MIME, signature, and basic text safety."""
    
    def validate(self, filename: str, data: bytes) -> Tuple[str, str]:
        """Return a safe filename and detected MIME type."""
        suffix = Path(filename).suffix.lower()

        self._check_extension(suffix)
        self._check_size(len(data))
        detected_mime = self._detect_mime(data)
        self._check_mime(suffix, detected_mime, data)
        self._check_magic_bytes(suffix, data)

        if suffix in _TEXT_EXTENSIONS:
            # HTML uploads are treated as source documents for parsing, not as
            # pages to render. Script tags can be stored as text, while dangerous
            # URL schemes are still blocked.
            self._scan_content(data, allow_html_scripts=suffix in {".html", ".htm"})

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
            stripped = data.lstrip()
            if stripped.startswith((b"{", b"[")):
                return "application/json"
            data.decode("utf-8")
            return "text/plain"
        except UnicodeDecodeError:
            return "application/octet-stream"
        
    def _check_mime(self, suffix: str, detected_mime: str, data: bytes) -> None:
        """Verify the detected MIME type is valid for the extension."""
        if suffix in _TEXT_EXTENSIONS and self._is_readable_text(data):
            # libmagic can mislabel short Markdown/code snippets as unrelated
            # formats such as video/MP2T. For source-like files, readable text
            # plus the extension allow-list is a better signal than MIME alone.
            return
        if suffix in {".html", ".htm"} and detected_mime == "application/octet-stream":
            return
        allowed = EXTENSION_MIME_MAP[suffix]
        if detected_mime not in allowed:
            raise UploadValidationError(
                f"Detected type '{detected_mime}' is not valid for '{suffix}'. "
                f"Expected one of: {sorted(allowed)}"
            )

    def _is_readable_text(self, data: bytes) -> bool:
        """Accept source/document text even when libmagic picks a narrow text subtype."""
        sample = data[:65_536]
        if b"\x00" in sample:
            return False

        try:
            text = sample.decode("utf-8")
        except UnicodeDecodeError:
            try:
                text = sample.decode("latin-1")
            except UnicodeDecodeError:
                return False

        if not text:
            return True

        readable = sum(1 for char in text if char.isprintable() or char in "\r\n\t")
        return readable / len(text) >= 0.92

    def _check_magic_bytes(self, suffix: str, data: bytes) -> None:
        """Verify binary formats start with their expected signature."""
        if suffix in {".html", ".htm"}:
            self._check_html_content(data)
            return
        expected = MAGIC_BYTES.get(suffix)
        if expected is not None and not data.startswith(expected):
            raise UploadValidationError(
                f"File does not begin with the expected '{suffix}' signature. "
                "It may be corrupt or incorrectly named."
            )

    def _check_html_content(self, data: bytes) -> None:
        """Accept HTML documents and fragments without requiring libmagic."""
        try:
            sample = data[:65_536].decode("utf-8", errors="ignore").lower()
        except Exception as exc:
            raise UploadValidationError("HTML files must be readable text.") from exc

        if not re.search(r"<!doctype\s+html|<html[\s>]|<(head|body|meta|title|div|p|span|a|section|article)[\s>]", sample):
            raise UploadValidationError(
                "HTML files must contain recognizable HTML markup."
            )
        
    def _scan_content(self, data: bytes, allow_html_scripts: bool = False) -> None:
        """Scan the first 64 KB of text formats for dangerous patterns."""
        sample = data[:65_536]
        patterns = _HTML_DANGER_PATTERNS if allow_html_scripts else _DANGER_PATTERNS
        for pattern in patterns:
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
