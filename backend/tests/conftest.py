"""Shared test setup for the backend suite."""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import pytest


# The application builds its SQLAlchemy engine while modules are imported. Set
# these before test modules import app code, otherwise it can open graphmind.db.
_TEST_ROOT = Path(tempfile.mkdtemp(prefix="graphmind-pytest-"))
_TEST_DB = _TEST_ROOT / "graphmind.sqlite3"
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB}"
os.environ["UPLOAD_DIR"] = str(_TEST_ROOT / "uploads")
# Keep no-Redis ticket tests explicit; production cases override the environment.
os.environ["WEBSOCKET_TICKET_MEMORY_FALLBACK"] = "true"


@pytest.fixture(scope="session", autouse=True)
def initialized_test_database():
    """Give every test run a fresh schema and remove it when pytest finishes."""
    from app.core.config import settings
    from app.core.database import engine, init_db

    Path(settings.UPLOAD_DIR).mkdir(parents=True, exist_ok=True)
    init_db()

    yield

    if engine is not None:
        engine.dispose()
    shutil.rmtree(_TEST_ROOT, ignore_errors=True)
