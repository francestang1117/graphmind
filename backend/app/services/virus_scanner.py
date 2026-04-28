"""Upload virus scanning interface.

The real ClamAV integration belongs in the security hardening phase. For the
current upload module we keep the boundary in place without making local
development depend on a running daemon.
"""


class VirusScanError(RuntimeError):
    """Raised when the scanner cannot complete a scan."""


class VirusFoundError(RuntimeError):
    """Raised when a scanner detects unsafe content."""

    def __init__(self, virus_name: str) -> None:
        self.virus_name = virus_name
        super().__init__(f"Virus detected: {virus_name}")


class VirusScanner:
    async def scan(self, data: bytes) -> None:
        """Accept bytes for now; replace with ClamAV later."""
        return None
