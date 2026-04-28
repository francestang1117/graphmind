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


def test_filename_sanitiser_strips_paths_and_bad_chars():
    assert FileValidator._sanitise_filename("../../bad<name>.md") == "bad_name_.md"
