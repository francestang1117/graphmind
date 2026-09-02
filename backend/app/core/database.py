"""SQLAlchemy setup for persistent app records."""

from __future__ import annotations

import logging
from typing import Iterator

from app.core.config import settings

log = logging.getLogger(__name__)

try:
    from sqlalchemy import create_engine, event
    from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
except ImportError:  # pragma: no cover - only used before dependencies are installed
    create_engine = None
    event = None
    DeclarativeBase = object  # type: ignore[assignment]
    Session = object  # type: ignore[assignment]
    sessionmaker = None


class Base(DeclarativeBase):  # type: ignore[misc, valid-type]
    """Base class for SQLAlchemy models."""


def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
    """Turn on SQLite referential actions for each pooled connection."""
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
    finally:
        cursor.close()


def _build_engine():
    if create_engine is None:
        log.warning("SQLAlchemy is not installed; database persistence disabled")
        return None

    database_url = settings.DATABASE_URL
    connect_args = {}
    if database_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False

    app_engine = create_engine(database_url, connect_args=connect_args, future=True)
    if database_url.startswith("sqlite") and event is not None:
        event.listen(app_engine, "connect", _enable_sqlite_foreign_keys)
    return app_engine


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
        GraphEdgeRecord,
        GraphNodeRecord,
        OAuthIdentityRecord,
        ParsedChunkRecord,
        ParsedEntityRecord,
        ProcessingJobRecord,
        UserRecord,
    )

    Base.metadata.create_all(bind=engine)

    # create_all does not change constraints on tables that already exist.
    # Run the small compatibility upgrade after the models are registered so
    # old local databases follow the same ownership rules as new ones.
    from app.core.database_migrations import upgrade_persistence_schema

    upgrade_persistence_schema(engine)


def get_db() -> Iterator[Session]:
    """FastAPI dependency for DB-backed endpoints."""
    if not SessionLocal:
        raise RuntimeError("Database is not configured")
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
