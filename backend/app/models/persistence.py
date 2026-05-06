"""SQLAlchemy models for users and uploaded document metadata."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class UserRecord(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120), default="")
    hashed_password: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class DocumentRecord(Base):
    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint("user_id", "file_hash", name="uq_documents_user_hash"),
    )

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    filename: Mapped[str] = mapped_column(String(255), index=True)
    stored_filename: Mapped[str] = mapped_column(String(255), index=True)
    original_filename: Mapped[str] = mapped_column(String(255))
    file_extension: Mapped[str] = mapped_column(String(32), default="")
    file_type: Mapped[str] = mapped_column(String(32), default="")
    mime_type: Mapped[str] = mapped_column(String(255), default="")
    file_hash: Mapped[str] = mapped_column(String(64), index=True)
    file_path: Mapped[str] = mapped_column(Text)
    file_size: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(32), default="uploaded")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    modified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
