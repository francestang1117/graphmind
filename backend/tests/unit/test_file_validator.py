"""Validator tests focus on upload safety rules that should not drift."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.utils.file_validator import FileValidator, UploadValidationError


@pytest.fixture
def validator():
    return FileValidator()


def test_markdown_upload_is_accepted(validator):
    fake_magic = SimpleNamespace(from_buffer=lambda *_args, **_kwargs: "text/plain")
    with patch("app.utils.file_validator.magic", fake_magic):
        safe_name, mime = validator.validate("../notes.md", b"# Title\n\nBody")

    assert safe_name == "notes.md"
    assert mime == "text/plain"


def test_markdown_heading_is_not_rejected_when_magic_calls_it_script_text(validator):
    fake_magic = SimpleNamespace(from_buffer=lambda *_args, **_kwargs: "text/x-shellscript")
    with patch("app.utils.file_validator.magic", fake_magic):
        safe_name, mime = validator.validate(
            "RAG System Design.md",
            b"# RAG System Design\n\nFastAPI uses Python for APIs.",
        )

    assert safe_name == "RAG System Design.md"
    assert mime == "text/x-shellscript"


def test_markdown_heading_is_not_rejected_when_magic_calls_it_video(validator):
    # libmagic sometimes reads a short "# Heading" markdown file as video/MP2T.
    # The validator should trust readable text for whitelisted text extensions.
    fake_magic = SimpleNamespace(from_buffer=lambda *_args, **_kwargs: "video/MP2T")
    with patch("app.utils.file_validator.magic", fake_magic):
        safe_name, mime = validator.validate(
            "RAG System Design.md",
            b"# RAG System Design\n\nFastAPI uses Python for APIs.",
        )

    assert safe_name == "RAG System Design.md"
    assert mime == "video/MP2T"


def test_binary_disguised_as_markdown_is_rejected(validator):
    fake_magic = SimpleNamespace(from_buffer=lambda *_args, **_kwargs: "video/MP2T")
    with patch("app.utils.file_validator.magic", fake_magic):
        with pytest.raises(UploadValidationError, match="Detected type"):
            validator.validate("not-notes.md", b"\x00\x01\x02\x03\x04")


@pytest.mark.parametrize("filename", ["app.exe", "archive.zip", "script.sh", "Makefile"])
def test_unlisted_extensions_are_rejected(validator, filename):
    with pytest.raises(UploadValidationError, match="not permitted"):
        validator.validate(filename, b"content")


def test_empty_file_is_rejected(validator):
    with pytest.raises(UploadValidationError, match="empty"):
        validator.validate("empty.txt", b"")


def test_pdf_must_have_pdf_bytes(validator):
    fake_magic = SimpleNamespace(from_buffer=lambda *_args, **_kwargs: "application/pdf")
    with patch("app.utils.file_validator.magic", fake_magic):
        with pytest.raises(UploadValidationError, match="signature"):
            validator.validate("fake.pdf", b"not a pdf")


def test_dangerous_text_content_is_rejected(validator):
    fake_magic = SimpleNamespace(from_buffer=lambda *_args, **_kwargs: "text/plain")
    with patch("app.utils.file_validator.magic", fake_magic):
        with pytest.raises(UploadValidationError, match="dangerous"):
            validator.validate("note.md", b"# Hi\n\n<script>alert(1)</script>")


def test_libmagic_failure_uses_local_fallback(validator):
    def fail(*_args, **_kwargs):
        raise RuntimeError("no magic")

    fake_magic = SimpleNamespace(from_buffer=fail)
    with patch("app.utils.file_validator.magic", fake_magic):
        safe_name, mime = validator.validate("fallback.txt", b"plain text")

    assert safe_name == "fallback.txt"
    assert mime == "text/plain"


def test_typescript_declaration_allows_json_like_mime(validator):
    # Short .d.ts files can be misidentified as JSON-ish text by libmagic.
    # They are still source text and should go through the code parser.
    fake_magic = SimpleNamespace(from_buffer=lambda *_args, **_kwargs: "application/json")
    with patch("app.utils.file_validator.magic", fake_magic):
        safe_name, mime = validator.validate("absolutePath.d.ts", b"{}")

    assert safe_name == "absolutePath.d.ts"
    assert mime == "application/json"


def test_filename_sanitiser_strips_paths_and_bad_chars():
    assert FileValidator._sanitise_filename("../../bad<name>.md") == "bad_name_.md"
