"""
Virus Scanner — ClamAV integration

Why we need it:
  Content-pattern scanning (file_validator) catches known injection payloads
  but cannot detect binary malware, novel exploits, or encoded payloads.
  ClamAV maintains a signature database updated daily covering:
  - Windows/Linux executables with malicious payloads
  - Office macro viruses
  - PDF exploits
  - Encrypted/obfuscated shellcode

Architecture:
  ClamAV runs as a separate daemon (clamd) in Docker.
  We stream file bytes to clamd over a socket — never touch disk.

  Upload flow with virus scan:
    1. file_validator.validate()   ← fast, in-memory
    2. virus_scanner.scan()        ← clamd stream scan (~50ms for 10MB)
    3. file_storage.save_file()    ← only on double-clean

Setup (docker-compose addition):
  clamav:
    image: clamav/clamav:stable
    ports: ["3310:3310"]
    volumes: ["clamav_data:/var/lib/clamav"]
    healthcheck:
      test: ["CMD", "clamdcheck.sh"]
      interval: 60s

Usage:
  result = virus_scanner.scan(content)
  if not result.clean:
      raise ValueError(f"Malware detected: {result.threat}")
"""

import logging
import socket
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger(__name__)


@dataclass
class ScanResult:
    clean:  bool
    threat: Optional[str] = None   # e.g. "Win.Malware.Agent-12345"
    source: str = "clamav"         # useful for logs/tests when clamd is absent
    error: Optional[str] = None    # connection/timeout/protocol details, not shown to users


class VirusScanner:
    """
    Stream-scan files via ClamAV daemon (clamd).

    Why streaming?
    - Never write suspicious bytes to disk before scanning
    - Works correctly in read-only container filesystems
    - Lower latency than file-based scan (~50ms vs ~200ms for a 10MB file)
    """

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
        """
        Scan bytes via INSTREAM command.

        ClamAV INSTREAM protocol:
          → "zINSTREAM\0"
          → 4-byte big-endian length, then chunk bytes (repeat)
          → 4-byte zero (end of stream)
          ← "stream: OK\n"  |  "stream: {threat} FOUND\n"
        """
        if not content:
            return ScanResult(clean=True, source="skipped-empty")

        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(self.timeout)
                s.connect((self.host, self.port))

                # Send INSTREAM command
                s.sendall(b"zINSTREAM\0")

                # Send content in 4 KB chunks
                chunk_size = 4096
                for i in range(0, len(content), chunk_size):
                    chunk  = content[i: i + chunk_size]
                    length = len(chunk).to_bytes(4, byteorder="big")
                    s.sendall(length + chunk)

                # End-of-stream sentinel
                s.sendall(b"\x00\x00\x00\x00")

                response = s.recv(1024).decode("utf-8", errors="replace").strip()

            result = self._parse_response(response)
            # ClamAV can answer with protocol/errors that are not malware names.
            # In production those should be treated like scanner outages.
            if result.source == "clamav-unexpected" and not self.fail_open:
                result.clean = False
            return result

        except ConnectionRefusedError:
            log.warning("ClamAV daemon unreachable at %s:%d", self.host, self.port)
            return self._unavailable("clamav-unavailable", "ClamAV daemon is unreachable")
        except OSError as exc:
            log.warning("ClamAV scan could not connect to %s:%d: %s", self.host, self.port, exc)
            return self._unavailable("clamav-unavailable", str(exc))
        except socket.timeout:
            log.warning("ClamAV scan timed out after %ds", self.timeout)
            return self._unavailable("clamav-timeout", "ClamAV scan timed out")
        except Exception as exc:
            log.error("ClamAV scan error: %s", exc)
            return self._unavailable("clamav-error", str(exc))

    def _unavailable(self, source: str, error: str) -> ScanResult:
        """Return an outage result according to the configured safety policy."""
        # fail_open=true keeps local development usable without Docker/clamd.
        # fail_open=false is for deployments where "could not scan" means "do
        # not accept the upload".
        return ScanResult(clean=self.fail_open, source=source, error=error)

    @staticmethod
    def _parse_response(response: str) -> ScanResult:
        """
        Parse clamd INSTREAM response.

        OK response:    "stream: OK"
        Threat response: "stream: Win.Malware.Agent-12345 FOUND"
        Error response:  "stream: ... ERROR"
        """
        if response.endswith("OK"):
            return ScanResult(clean=True)
        if "FOUND" in response:
            # Extract threat name between ": " and " FOUND"
            try:
                threat = response.split(": ")[1].replace(" FOUND", "").strip()
            except IndexError:
                threat = "Unknown"
            log.warning("Malware detected: %s", threat)
            return ScanResult(clean=False, threat=threat)
        # ERROR or unexpected — treat as unavailable
        log.error("Unexpected ClamAV response: %s", response)
        return ScanResult(clean=True, source="clamav-unexpected", error=response)


# ── Singleton ─────────────────────────────────────────────────────────────────
try:
    from app.core.config import settings
    virus_scanner = VirusScanner(
        host=getattr(settings, "CLAMAV_HOST", "clamav"),
        port=getattr(settings, "CLAMAV_PORT", 3310),
        timeout=getattr(settings, "CLAMAV_TIMEOUT_SECONDS", 30),
        fail_open=getattr(settings, "VIRUS_SCAN_FAIL_OPEN", True),
    )
except Exception:
    virus_scanner = VirusScanner()
