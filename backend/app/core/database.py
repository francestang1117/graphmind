"""SQLAlchemy setup for persistent app records."""

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
    from app.models.persistence import (  # noqa: F401
        DocumentRecord,
        ParsedChunkRecord,
        ParsedEntityRecord,
        UserRecord,
    )

    Base.metadata.create_all(bind=engine)


def get_db() -> Iterator[Session]:
    """FastAPI dependency for DB-backed endpoints."""
    if not SessionLocal:
        raise RuntimeError("Database is not configured")
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
