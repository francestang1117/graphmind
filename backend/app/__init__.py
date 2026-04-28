"""Application package initialization."""

from pathlib import Path

from app.core.config import settings


def init_app() -> None:
    """Create local runtime directories required by the app."""
    Path(settings.UPLOAD_DIR).mkdir(parents=True, exist_ok=True)
