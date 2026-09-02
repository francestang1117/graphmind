"""Database access for research workspaces."""

from __future__ import annotations

import logging
import uuid
from typing import Any, Callable, Optional

from app.core.database import SessionLocal, db_enabled
from app.core.errors import DatabaseOperationError
from app.core.workspace import (
    DEFAULT_WORKSPACE_DOMAIN,
    DEFAULT_WORKSPACE_NAME,
    DEFAULT_WORKSPACE_STATUS,
    default_workspace_id,
)

log = logging.getLogger(__name__)

try:
    from sqlalchemy import select
    from sqlalchemy.exc import SQLAlchemyError
    from app.models.persistence import WorkspaceRecord, utc_now
except ImportError:  # pragma: no cover - only before DB dependencies are installed
    select = None
    SQLAlchemyError = Exception
    WorkspaceRecord = None  # type: ignore[assignment]
    utc_now = None  # type: ignore[assignment]


class WorkspaceRepository:
    """Keep workspace reads and ownership checks in one place."""

    def __init__(
        self,
        session_factory=SessionLocal,
        enabled: Callable[[], bool] = db_enabled,
    ) -> None:
        self.session_factory = session_factory
        self.enabled = enabled

    def available(self) -> bool:
        return bool(self.enabled() and self.session_factory and select and WorkspaceRecord)

    def ensure_default(self, user_id: str) -> dict[str, Any] | None:
        """Create the compatibility project the first time a user needs it."""
        workspace_id = default_workspace_id(user_id)
        if not self.available():
            return None

        try:
            with self.session_factory() as db:
                record = db.get(WorkspaceRecord, workspace_id)
                if not record:
                    now = utc_now()
                    record = WorkspaceRecord(
                        id=workspace_id,
                        user_id=user_id,
                        name=DEFAULT_WORKSPACE_NAME,
                        research_question="",
                        domain=DEFAULT_WORKSPACE_DOMAIN,
                        status=DEFAULT_WORKSPACE_STATUS,
                        created_at=now,
                        updated_at=now,
                    )
                    db.add(record)
                    db.commit()
                return _record_to_dict(record)
        except (SQLAlchemyError, OSError, RuntimeError) as exc:
            _raise_db_error("ensure default workspace", exc, {"user_id": user_id})

    def create(
        self,
        user_id: str,
        name: str,
        research_question: str = "",
        domain: str = DEFAULT_WORKSPACE_DOMAIN,
    ) -> dict[str, Any]:
        if not self.available():
            raise DatabaseOperationError(
                "Workspace database is unavailable.",
                details={"operation": "create workspace"},
            )

        now = utc_now()
        record = WorkspaceRecord(
            id=uuid.uuid4().hex,
            user_id=user_id,
            name=name.strip(),
            research_question=research_question.strip(),
            domain=domain.strip().lower() or DEFAULT_WORKSPACE_DOMAIN,
            status="active",
            created_at=now,
            updated_at=now,
        )
        try:
            with self.session_factory() as db:
                db.add(record)
                db.commit()
                db.refresh(record)
                return _record_to_dict(record)
        except (SQLAlchemyError, OSError, RuntimeError) as exc:
            _raise_db_error("create workspace", exc, {"user_id": user_id})

    def list(self, user_id: str) -> list[dict[str, Any]]:
        if not self.available():
            return []

        try:
            self.ensure_default(user_id)
            with self.session_factory() as db:
                stmt = (
                    select(WorkspaceRecord)
                    .where(WorkspaceRecord.user_id == user_id)
                    .order_by(WorkspaceRecord.updated_at.desc(), WorkspaceRecord.created_at.desc())
                )
                return [_record_to_dict(item) for item in db.scalars(stmt).all()]
        except (SQLAlchemyError, OSError, RuntimeError) as exc:
            _raise_db_error("list workspaces", exc, {"user_id": user_id})

    def get(self, workspace_id: str, user_id: str) -> Optional[dict[str, Any]]:
        if not self.available():
            return None

        try:
            with self.session_factory() as db:
                record = db.scalars(
                    select(WorkspaceRecord).where(
                        WorkspaceRecord.id == workspace_id,
                        WorkspaceRecord.user_id == user_id,
                    )
                ).first()
                return _record_to_dict(record) if record else None
        except (SQLAlchemyError, OSError, RuntimeError) as exc:
            _raise_db_error(
                "get workspace",
                exc,
                {"workspace_id": workspace_id, "user_id": user_id},
            )


def _record_to_dict(record: "WorkspaceRecord") -> dict[str, Any]:
    return {
        "id": record.id,
        "user_id": record.user_id,
        "name": record.name,
        "research_question": record.research_question,
        "domain": record.domain,
        "status": record.status,
        "created_at": record.created_at.isoformat() if record.created_at else "",
        "updated_at": record.updated_at.isoformat() if record.updated_at else "",
    }


def _raise_db_error(operation: str, exc: Exception, details: dict[str, Any]) -> None:
    log.warning("Could not %s: %s", operation, exc)
    raise DatabaseOperationError(
        "Workspace database is unavailable.",
        details={"operation": operation, **details},
    ) from exc


workspace_repository = WorkspaceRepository()
