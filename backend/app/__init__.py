"""Application package initialization."""

from pathlib import Path


def init_app() -> None:
    """Create local runtime directories and optional database tables."""
    from app.core.config import settings
    from app.core.database import init_db

    Path(settings.UPLOAD_DIR).mkdir(parents=True, exist_ok=True)
    init_db()
