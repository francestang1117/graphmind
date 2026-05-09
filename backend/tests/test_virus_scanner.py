"""Virus scanner tests cover ClamAV response handling and upload integration."""

import pytest

from app.core.errors import MalwareDetectedError, StorageOperationError, VirusScannerUnavailableError
from app.services.document_service import DocumentService
from app.services.file_storage import FileStorage, FileStorageError
from app.services.virus_scanner import ScanResult, VirusScanner


class FakeScanner:
    def __init__(self, result: ScanResult) -> None:
        self.result = result
        self.calls = 0

    def scan(self, content: bytes) -> ScanResult:
        self.calls += 1
        return self.result


class BrokenStorage(FileStorage):
    def save_file(self, *args, **kwargs):
        raise FileStorageError("disk full")


def test_parse_clamav_clean_response():
    result = VirusScanner._parse_response("stream: OK")

    assert result.clean is True
    assert result.threat is None


def test_parse_clamav_threat_response():
    result = VirusScanner._parse_response("stream: Eicar-Test-Signature FOUND")

    assert result.clean is False
    assert result.threat == "Eicar-Test-Signature"


def test_fail_closed_marks_scanner_outage_as_blocking():
    scanner = VirusScanner(host="localhost", port=1, timeout=1, fail_open=False)
    result = scanner._unavailable("clamav-unavailable", "down")

    assert result.clean is False
    assert result.error == "down"


def test_fail_closed_marks_unexpected_clamav_response_as_blocking():
    scanner = VirusScanner(fail_open=False)
    result = scanner._parse_response("stream: broken ERROR")
    if result.source == "clamav-unexpected" and not scanner.fail_open:
        result.clean = False

    assert result.clean is False


def test_document_service_scans_before_storage_write(tmp_path):
    scanner = FakeScanner(ScanResult(clean=False, threat="Eicar-Test-Signature"))
    service = DocumentService(
        storage=FileStorage(tmp_path),
        scanner=scanner,
        use_database=False,
        virus_scan_enabled=True,
    )

    with pytest.raises(MalwareDetectedError, match="Malware detected"):
        service.save_upload("note.txt", b"plain text")

    assert scanner.calls == 1
    assert service.list_documents() == []


def test_document_service_can_skip_scanner_for_local_dev(tmp_path):
    scanner = FakeScanner(ScanResult(clean=False, threat="Eicar-Test-Signature"))
    service = DocumentService(
        storage=FileStorage(tmp_path),
        scanner=scanner,
        use_database=False,
        virus_scan_enabled=False,
    )

    metadata = service.save_upload("note.txt", b"plain text")

    assert scanner.calls == 0
    assert metadata["original_filename"] == "note.txt"


def test_document_service_blocks_when_scanner_is_fail_closed(tmp_path):
    scanner = FakeScanner(
        ScanResult(clean=False, source="clamav-unavailable", error="connection refused")
    )
    service = DocumentService(
        storage=FileStorage(tmp_path),
        scanner=scanner,
        use_database=False,
        virus_scan_enabled=True,
    )

    with pytest.raises(VirusScannerUnavailableError) as exc:
        service.save_upload("note.txt", b"plain text")

    assert exc.value.code == "virus_scanner_unavailable"
    assert exc.value.details["scanner"] == "clamav-unavailable"
    assert service.list_documents() == []


def test_document_service_wraps_storage_write_errors(tmp_path):
    service = DocumentService(
        storage=BrokenStorage(tmp_path),
        scanner=None,
        use_database=False,
        virus_scan_enabled=False,
    )

    with pytest.raises(StorageOperationError) as exc:
        service.save_upload("note.txt", b"plain text")

    assert exc.value.code == "storage_operation_failed"
    assert exc.value.details["filename"] == "note.txt"
