"""Database foundation.

The current app still uses local sidecar metadata as its primary read path.
This module is the first persistence layer: when SQLAlchemy is installed, it
creates the core tables and lets services mirror important state into the DB.

PostgreSQL is the production target, but SQLite keeps local development and
tests lightweight until the rest of the persistence layer is ready.
"""

from __future__ import annotations

import logging
from typing import Iterator

from app.core.config import settings

log = logging.getLogger(__name__)

try:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
except ImportError:  # pragma: no cover - only used before dependencies are installed
    create_engine = None
    DeclarativeBase = object  # type: ignore[assignment]
    Session = object  # type: ignore[assignment]
    sessionmaker = None


class Base(DeclarativeBase):  # type: ignore[misc, valid-type]
    """Base class for SQLAlchemy models."""


def _build_engine():
    if create_engine is None:
        log.warning("SQLAlchemy is not installed; database persistence disabled")
        return None

    connect_args = {}
    if settings.DATABASE_URL.startswith("sqlite"):
        connect_args["check_same_thread"] = False

    return create_engine(settings.DATABASE_URL, connect_args=connect_args, future=True)


engine = _build_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True) if engine else None


def db_enabled() -> bool:
    """Return whether the SQLAlchemy persistence layer is available."""
    return engine is not None and SessionLocal is not None


def init_db() -> None:
    """Create tables for the current lightweight persistence layer."""
    if not db_enabled():
        return

    # Import models here so Base.metadata knows about them without creating an
    # import cycle during module import.
    from app.models.persistence import DocumentRecord, UserRecord  # noqa: F401

    Base.metadata.create_all(bind=engine)


def get_db() -> Iterator[Session]:
    """FastAPI dependency for future DB-backed endpoints."""
    if not SessionLocal:
        raise RuntimeError("Database is not configured")
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
