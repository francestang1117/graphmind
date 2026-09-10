"""SQLAlchemy models for users and uploaded document metadata."""

from __future__ import annotations

from datetime import datetime, timezone
import uuid

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
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
    # Medical fields are nullable so older uploads remain valid after the
    # migration. The profile table holds the full analysis result.
    document_kind: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    source_kind: Mapped[str | None] = mapped_column(String(64), nullable=True, default="user_upload")
    language: Mapped[str | None] = mapped_column(String(16), nullable=True)
    document_date: Mapped[str | None] = mapped_column(String(32), nullable=True)
    parser_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Updated when parsing commits a new profile, sections, and chunk set.
    # Analysis status checks this scalar instead of hashing the whole document.
    parsed_source_hash: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True
    )
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


class MedicalDocumentProfileRecord(Base):
    """The explainable medical classification for one document."""
    __tablename__ = "medical_document_profiles"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "workspace_id",
            "document_id",
            name="uq_medical_profiles_user_workspace_document",
        ),
    )

    id: Mapped[str] = mapped_column(String(320), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    workspace_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    document_id: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("documents.id", ondelete="CASCADE"),
        index=True,
    )
    document_kind: Mapped[str] = mapped_column(String(64), default="unknown", index=True)
    language: Mapped[str] = mapped_column(String(16), default="unknown")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    classifier_version: Mapped[str] = mapped_column(String(64), default="medical-rules-v1")
    signals_json: Mapped[str] = mapped_column(Text, default="[]")
    warnings_json: Mapped[str] = mapped_column(Text, default="[]")
    missing_sections_json: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class DocumentSectionRecord(Base):
    """A paper section with the page and character range it came from."""

    __tablename__ = "document_sections"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "workspace_id",
            "document_id",
            "ordinal",
            name="uq_document_sections_user_workspace_document_ordinal",
        ),
    )

    id: Mapped[str] = mapped_column(String(320), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    workspace_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    document_id: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("documents.id", ondelete="CASCADE"),
        index=True,
    )
    section_type: Mapped[str] = mapped_column(String(64), default="unknown", index=True)
    original_title: Mapped[str] = mapped_column(String(255), default="")
    ordinal: Mapped[int] = mapped_column(Integer)
    page_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    char_start: Mapped[int] = mapped_column(Integer, default=0)
    char_end: Mapped[int] = mapped_column(Integer, default=0)
    text: Mapped[str] = mapped_column(Text, default="")
    language: Mapped[str] = mapped_column(String(16), default="unknown")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


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


class MedicalAnalysisRunRecord(Base):
    """One versioned request to explain a medical document."""

    __tablename__ = "medical_analysis_runs"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "workspace_id",
            "document_id",
            "analysis_key",
            name="uq_medical_analysis_run_version",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    workspace_id: Mapped[str] = mapped_column(String(64), index=True)
    document_id: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("documents.id", ondelete="CASCADE"),
        index=True,
    )
    requested_by: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    source_hash: Mapped[str] = mapped_column(String(64), index=True)
    # Hash of the parsed profile, sections, and chunks used by this run. A
    # file can keep the same bytes while parser output changes.
    parsed_source_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    analysis_key: Mapped[str] = mapped_column(String(255), index=True)
    provider: Mapped[str] = mapped_column(String(64), default="extractive")
    model_name: Mapped[str] = mapped_column(String(128), default="extractive-v1")
    prompt_version: Mapped[str] = mapped_column(String(64), default="medical-insights-v2")
    schema_version: Mapped[str] = mapped_column(String(64), default="medical-insights-v2")
    redact_pii: Mapped[bool] = mapped_column(Boolean, default=True)
    max_input_tokens: Mapped[int] = mapped_column(Integer, default=12000)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=30)
    max_output_tokens: Mapped[int] = mapped_column(Integer, default=5000)
    provider_retry_count: Mapped[int] = mapped_column(Integer, default=2)
    external_processing_confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    error_code: Mapped[str] = mapped_column(String(80), default="")
    error_message: Mapped[str] = mapped_column(Text, default="")
    is_current: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class MedicalAnalysisResultRecord(Base):
    """Validated report attached to one analysis run."""

    __tablename__ = "medical_analysis_results"

    run_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("medical_analysis_runs.id", ondelete="CASCADE"),
        primary_key=True,
    )
    report_json: Mapped[str] = mapped_column(Text)
    citation_coverage: Mapped[float] = mapped_column(Float, default=0.0)
    validation_status: Mapped[str] = mapped_column(String(32), default="validated")
    warnings_json: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class MedicalAnalysisEvidenceRecord(Base):
    """A saved link from a report finding to source text."""

    __tablename__ = "medical_analysis_evidence"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    # This is the id shown in the report, for example EVIDENCE_001. Keep it
    # separate from the database row id so the API can map citations back to
    # the context that was sent to the provider.
    evidence_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    run_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("medical_analysis_runs.id", ondelete="CASCADE"),
        index=True,
    )
    finding_id: Mapped[str] = mapped_column(String(128), index=True)
    chunk_id: Mapped[str] = mapped_column(String(320), index=True)
    section_id: Mapped[str | None] = mapped_column(String(320), nullable=True, index=True)
    section_type: Mapped[str] = mapped_column(String(64), default="unknown")
    section_title: Mapped[str] = mapped_column(String(255), default="")
    page_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quoted_text: Mapped[str] = mapped_column(Text)
    character_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    character_end: Mapped[int | None] = mapped_column(Integer, nullable=True)


class LiteratureSearchRunRecord(Base):
    """One privacy-bounded literature search requested for a document."""

    __tablename__ = "literature_search_runs"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "workspace_id",
            "document_id",
            "query_hash",
            "provider",
            name="uq_literature_search_runs_scope_query_provider",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    workspace_id: Mapped[str] = mapped_column(String(64), index=True)
    document_id: Mapped[str | None] = mapped_column(
        String(255),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    question: Mapped[str] = mapped_column(Text, default="")
    normalized_query: Mapped[str] = mapped_column(Text)
    query_hash: Mapped[str] = mapped_column(String(64), index=True)
    provider: Mapped[str] = mapped_column(String(64), default="pubmed", index=True)
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    date_from: Mapped[str | None] = mapped_column(String(32), nullable=True)
    date_to: Mapped[str | None] = mapped_column(String(32), nullable=True)
    study_types_json: Mapped[str] = mapped_column(Text, default="[]")
    sort: Mapped[str] = mapped_column(String(32), default="relevance")
    max_results: Mapped[int] = mapped_column(Integer, default=20)
    result_count: Mapped[int] = mapped_column(Integer, default=0)
    error_code: Mapped[str] = mapped_column(String(80), default="")
    error_message: Mapped[str] = mapped_column(Text, default="")
    warnings_json: Mapped[str] = mapped_column(Text, default="[]")
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    external_search_confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class LiteratureArticleRecord(Base):
    """Normalized public metadata cached from a literature provider."""

    __tablename__ = "literature_articles"
    __table_args__ = (
        UniqueConstraint(
            "source",
            "external_id",
            name="uq_literature_articles_source_external",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source: Mapped[str] = mapped_column(String(64), default="pubmed", index=True)
    external_id: Mapped[str] = mapped_column(String(128), index=True)
    doi: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    pmcid: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    title: Mapped[str] = mapped_column(Text, default="")
    abstract: Mapped[str] = mapped_column(Text, default="")
    journal: Mapped[str] = mapped_column(String(512), default="")
    publication_date: Mapped[str] = mapped_column(String(32), default="")
    publication_year: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    authors_json: Mapped[str] = mapped_column(Text, default="[]")
    publication_types_json: Mapped[str] = mapped_column(Text, default="[]")
    mesh_terms_json: Mapped[str] = mapped_column(Text, default="[]")
    language: Mapped[str] = mapped_column(String(32), default="")
    source_url: Mapped[str] = mapped_column(String(512), default="")
    retraction_status: Mapped[str] = mapped_column(String(32), default="unknown", index=True)
    metadata_hash: Mapped[str] = mapped_column(String(64), default="", index=True)
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class LiteratureSearchResultRecord(Base):
    """The ranked article list returned by one search run."""

    __tablename__ = "literature_search_results"
    __table_args__ = (
        UniqueConstraint(
            "search_run_id",
            "article_id",
            name="uq_literature_search_results_run_article",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    search_run_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("literature_search_runs.id", ondelete="CASCADE"),
        index=True,
    )
    article_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("literature_articles.id", ondelete="CASCADE"),
        index=True,
    )
    provider_rank: Mapped[int] = mapped_column(Integer, default=0)
    matched_terms_json: Mapped[str] = mapped_column(Text, default="[]")
    selected_for_analysis: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
