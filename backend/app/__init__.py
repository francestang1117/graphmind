"""Application package initialization."""

from pathlib import Path


def init_app() -> None:
    """Create local runtime directories required by the app."""
    from app.core.config import settings

    Path(settings.UPLOAD_DIR).mkdir(parents=True, exist_ok=True)
