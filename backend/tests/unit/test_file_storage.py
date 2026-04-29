"""Storage tests keep the upload layer honest without touching real files."""

from pathlib import Path

import pytest

from app.services.file_storage import DuplicateFileError, FileStorage, _sha256


def test_save_file_returns_metadata_and_writes_bytes(tmp_path):
    storage = FileStorage(tmp_path)
    content = b"# Notes\n\nHello."

    info = storage.save_file(content, "notes.md", "text/plain")

    assert info["original_filename"] == "notes.md"
    assert info["file_hash"] == _sha256(content)
    assert Path(info["file_path"]).read_bytes() == content


def test_same_content_is_reported_as_duplicate(tmp_path):
    storage = FileStorage(tmp_path)

    first = storage.save_file(b"same", "first.txt", "text/plain")

    with pytest.raises(DuplicateFileError) as exc:
        storage.save_file(b"same", "second.txt", "text/plain")

    assert exc.value.metadata["file_path"] == first["file_path"]
    assert exc.value.metadata["file_hash"] == first["file_hash"]


def test_list_files_returns_saved_metadata(tmp_path):
    storage = FileStorage(tmp_path)

    storage.save_file(b"one", "one.txt", "text/plain")
    storage.save_file(b"two", "two.txt", "text/plain")

    files = storage.list_files()
    names = {item["original_filename"] for item in files}
    assert names == {"one.txt", "two.txt"}


def test_load_and_delete_by_stored_filename(tmp_path):
    storage = FileStorage(tmp_path)
    info = storage.save_file(b"delete me", "delete.txt", "text/plain")

    assert storage.load_file(info["stored_filename"]) == b"delete me"
    assert storage.delete_file(info["stored_filename"]) is True
    assert storage.get_file_info(info["stored_filename"]) is None


def test_missing_file_operations_are_predictable(tmp_path):
    storage = FileStorage(tmp_path)

    assert storage.delete_file("missing.txt") is False
    with pytest.raises(FileNotFoundError):
        storage.load_file("missing.txt")
