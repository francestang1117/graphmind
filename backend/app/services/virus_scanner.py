"""Small ClamAV wrapper used by the upload flow."""

import logging
import socket
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger(__name__)


@dataclass
class ScanResult:
    clean:  bool
    threat: Optional[str] = None
    source: str = "clamav"
    error: Optional[str] = None


class VirusScanner:
    """Send upload bytes to clamd without saving them first."""

    def __init__(
        self,
        host: str = "clamav",
        port: int = 3310,
        timeout: int = 30,
        fail_open: bool = True,
    ):
        self.host    = host
        self.port    = port
        self.timeout = timeout
        self.fail_open = fail_open

    def scan(self, content: bytes) -> ScanResult:
        """Return a clean/threat result for one upload body."""
        if not content:
            return ScanResult(clean=True, source="skipped-empty")

        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(self.timeout)
                s.connect((self.host, self.port))

                # clamd's INSTREAM protocol accepts length-prefixed chunks, so
                # uploads can be scanned before they ever touch disk.
                s.sendall(b"zINSTREAM\0")

                chunk_size = 4096
                for i in range(0, len(content), chunk_size):
                    chunk  = content[i: i + chunk_size]
                    length = len(chunk).to_bytes(4, byteorder="big")
                    s.sendall(length + chunk)

                s.sendall(b"\x00\x00\x00\x00")

                response = s.recv(1024).decode("utf-8", errors="replace").strip()

            result = self._parse_response(response)
            # Strict mode treats weird clamd replies as blocked.
            if result.source == "clamav-unexpected" and not self.fail_open:
                result.clean = False
            return result

        except socket.timeout:
            log.warning("ClamAV scan timed out after %ds", self.timeout)
            return self._unavailable("clamav-timeout", "ClamAV scan timed out")
        except ConnectionRefusedError:
            log.warning("ClamAV daemon unreachable at %s:%d", self.host, self.port)
            return self._unavailable("clamav-unavailable", "ClamAV daemon is unreachable")
        except OSError as exc:
            log.warning("ClamAV scan could not connect to %s:%d: %s", self.host, self.port, exc)
            return self._unavailable("clamav-unavailable", str(exc))

    def _unavailable(self, source: str, error: str) -> ScanResult:
        """Handle the case where clamd is down or unreachable."""
        # Local dev can fail open so the app is usable without Docker services.
        # Docker/prod should normally fail closed through settings.
        return ScanResult(clean=self.fail_open, source=source, error=error)

    @staticmethod
    def _parse_response(response: str) -> ScanResult:
        """Parse clamd's one-line scan response."""
        if response.endswith("OK"):
            return ScanResult(clean=True)
        if "FOUND" in response:
            try:
                threat = response.split(": ")[1].replace(" FOUND", "").strip()
            except IndexError:
                threat = "Unknown"
            log.warning("Malware detected: %s", threat)
            return ScanResult(clean=False, threat=threat)
        log.error("Unexpected ClamAV response: %s", response)
        return ScanResult(clean=True, source="clamav-unexpected", error=response)


try:
    from app.core.config import settings
    virus_scanner = VirusScanner(
        host=getattr(settings, "CLAMAV_HOST", "clamav"),
        port=getattr(settings, "CLAMAV_PORT", 3310),
        timeout=getattr(settings, "CLAMAV_TIMEOUT_SECONDS", 30),
        fail_open=getattr(settings, "VIRUS_SCAN_FAIL_OPEN", True),
    )
except (ImportError, AttributeError):
    virus_scanner = VirusScanner()
