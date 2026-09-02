"""SQLAlchemy models for users and uploaded document metadata."""

from __future__ import annotations

from datetime import datetime, timezone
import uuid

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
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


class OAuthIdentityRecord(Base):
    """External account id mapped to the local user that owns the workspace."""

    __tablename__ = "oauth_identities"
    __table_args__ = (
        UniqueConstraint("provider", "provider_user_id", name="uq_oauth_provider_user"),
    )

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), index=True)
    provider_user_id: Mapped[str] = mapped_column(String(255), index=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class WorkspaceRecord(Base):
    """A user's research area; every document and derived row belongs to one."""

    __tablename__ = "workspaces"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(160))
    research_question: Mapped[str] = mapped_column(Text, default="")
    domain: Mapped[str] = mapped_column(String(64), default="medical", index=True)
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class DocumentRecord(Base):
    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "workspace_id",
            "file_hash",
            name="uq_documents_user_workspace_hash",
        ),
    )

    # A content hash identifies bytes, not a user's document row. Keep those
    # two identities separate so the same file can belong to two users.
    id: Mapped[str] = mapped_column(
        String(255),
        primary_key=True,
        default=lambda: uuid.uuid4().hex,
    )
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    workspace_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
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


class ParsedChunkRecord(Base):
    """Reusable text slices from a parsed document.

    Search, chat, and later vector indexing should read these rows instead of
    reparsing the original file every time.
    """

    __tablename__ = "parsed_chunks"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "workspace_id",
            "document_id",
            "chunk_index",
            name="uq_chunks_user_workspace_document_index",
        ),
    )

    id: Mapped[str] = mapped_column(String(320), primary_key=True)
    document_id: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("documents.id", ondelete="CASCADE"),
        index=True,
    )
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    workspace_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    chunk_index: Mapped[int] = mapped_column(Integer)
    chunk_type: Mapped[str] = mapped_column(String(64), default="text")
    text: Mapped[str] = mapped_column(Text)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ParsedEntityRecord(Base):
    """Entities extracted from one document.

    These rows are the bridge between the parser/NER work and the graph layer:
    the graph can rebuild nodes from here without opening the uploaded file.
    """

    __tablename__ = "parsed_entities"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "workspace_id",
            "document_id",
            "normalized",
            "label",
            name="uq_entities_user_workspace_document_name_label",
        ),
    )

    id: Mapped[str] = mapped_column(String(320), primary_key=True)
    document_id: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("documents.id", ondelete="CASCADE"),
        index=True,
    )
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    workspace_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    text: Mapped[str] = mapped_column(String(255), index=True)
    normalized: Mapped[str] = mapped_column(String(255), index=True)
    label: Mapped[str] = mapped_column(String(80), default="ENTITY", index=True)
    source: Mapped[str] = mapped_column(String(80), default="")
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    context: Mapped[str] = mapped_column(Text, default="")
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class GraphNodeRecord(Base):
    """One persisted graph node.

    Nodes can be shared by several documents, so sources are kept as JSON text
    for now. A join table can come later if graph history gets more serious.
    """

    __tablename__ = "graph_nodes"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "workspace_id",
            "node_id",
            name="uq_graph_nodes_user_workspace_node",
        ),
    )

    id: Mapped[str] = mapped_column(String(320), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    workspace_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    node_id: Mapped[str] = mapped_column(String(255), index=True)
    label: Mapped[str] = mapped_column(String(255), index=True)
    node_type: Mapped[str] = mapped_column(String(80), default="ENTITY", index=True)
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    sources_json: Mapped[str] = mapped_column(Text, default="[]")
    source_document_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    properties_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class GraphEdgeRecord(Base):
    """One persisted graph edge for a source document.

    Storing source_document_id on the edge keeps reindex/delete scoped to one
    file instead of forcing a full graph rebuild.
    """

    __tablename__ = "graph_edges"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "workspace_id",
            "source_node_id",
            "target_node_id",
            "relation_type",
            "source_document_id",
            name="uq_graph_edges_user_workspace_relation_doc",
        ),
    )

    id: Mapped[str] = mapped_column(String(320), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    workspace_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    source_node_id: Mapped[str] = mapped_column(String(255), index=True)
    target_node_id: Mapped[str] = mapped_column(String(255), index=True)
    relation_type: Mapped[str] = mapped_column(String(80), default="RELATED_TO", index=True)
    source_document_id: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("documents.id", ondelete="CASCADE"),
        index=True,
    )
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    weight: Mapped[int] = mapped_column(Integer, default=1)
    sources_json: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ProcessingJobRecord(Base):
    """One background job as the app sees it.

    Celery owns execution; this table gives the API and UI a stable place to
    look after a refresh or after the WebSocket has gone away.
    """

    __tablename__ = "processing_jobs"

    job_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    workspace_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    document_id: Mapped[str | None] = mapped_column(
        String(255),
        ForeignKey("documents.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    original_filename: Mapped[str] = mapped_column(String(255), default="")
    status: Mapped[str] = mapped_column(String(32), default="PENDING", index=True)
    step: Mapped[str] = mapped_column(String(255), default="Queued")
    progress: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    # Only filled once the job is no longer active. Cleanup uses this instead
    # of updated_at so a long-running job is never removed by age alone.
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
