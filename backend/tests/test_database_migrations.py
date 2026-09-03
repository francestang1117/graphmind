"""Regression checks for upgrading the old hash-keyed persistence schema."""

import os
import uuid

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from app.core.database import Base
from app.core.database_migrations import upgrade_persistence_schema
from app.core.workspace import default_workspace_id
from app.models.persistence import (
    DocumentRecord,
    GraphEdgeRecord,
    ParsedChunkRecord,
    ParsedEntityRecord,
    ProcessingJobRecord,
    UserRecord,
    WorkspaceRecord,
)


def _legacy_engine():
    engine = create_engine("sqlite:///:memory:", future=True)
    with engine.begin() as db:
        db.exec_driver_sql(
            """
            CREATE TABLE documents (
                id VARCHAR(255) PRIMARY KEY,
                user_id VARCHAR(64) NOT NULL,
                filename VARCHAR(255) NOT NULL,
                stored_filename VARCHAR(255) NOT NULL,
                original_filename VARCHAR(255) NOT NULL,
                file_extension VARCHAR(32) NOT NULL,
                file_type VARCHAR(32) NOT NULL,
                mime_type VARCHAR(255) NOT NULL,
                file_hash VARCHAR(64) NOT NULL,
                file_path TEXT NOT NULL,
                file_size INTEGER NOT NULL,
                status VARCHAR(32) NOT NULL,
                created_at DATETIME NOT NULL,
                modified_at DATETIME NOT NULL,
                deleted_at DATETIME
            )
            """
        )
        db.exec_driver_sql(
            """
            CREATE TABLE parsed_chunks (
                id VARCHAR(320) PRIMARY KEY,
                document_id VARCHAR(255) NOT NULL,
                user_id VARCHAR(64) NOT NULL,
                chunk_index INTEGER NOT NULL,
                chunk_type VARCHAR(64) NOT NULL,
                text TEXT NOT NULL,
                metadata_json TEXT NOT NULL,
                created_at DATETIME NOT NULL,
                UNIQUE (document_id, chunk_index)
            )
            """
        )
        db.exec_driver_sql(
            """
            CREATE TABLE parsed_entities (
                id VARCHAR(320) PRIMARY KEY,
                document_id VARCHAR(255) NOT NULL,
                user_id VARCHAR(64) NOT NULL,
                text VARCHAR(255) NOT NULL,
                normalized VARCHAR(255) NOT NULL,
                label VARCHAR(80) NOT NULL,
                source VARCHAR(80) NOT NULL,
                confidence FLOAT NOT NULL,
                context TEXT NOT NULL,
                metadata_json TEXT NOT NULL,
                created_at DATETIME NOT NULL,
                UNIQUE (document_id, normalized, label)
            )
            """
        )
        db.exec_driver_sql(
            """
            CREATE TABLE graph_edges (
                id VARCHAR(320) PRIMARY KEY,
                user_id VARCHAR(64) NOT NULL,
                source_node_id VARCHAR(255) NOT NULL,
                target_node_id VARCHAR(255) NOT NULL,
                relation_type VARCHAR(80) NOT NULL,
                source_document_id VARCHAR(255) NOT NULL,
                confidence FLOAT NOT NULL,
                weight INTEGER NOT NULL,
                sources_json TEXT NOT NULL,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                UNIQUE (user_id, source_node_id, target_node_id, relation_type, source_document_id)
            )
            """
        )
        db.exec_driver_sql(
            """
            CREATE TABLE processing_jobs (
                job_id VARCHAR(255) PRIMARY KEY,
                user_id VARCHAR(64) NOT NULL,
                document_id VARCHAR(255) NOT NULL,
                original_filename VARCHAR(255) NOT NULL,
                status VARCHAR(32) NOT NULL,
                step VARCHAR(255) NOT NULL,
                progress INTEGER NOT NULL,
                error TEXT NOT NULL,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                finished_at DATETIME
            )
            """
        )
        db.exec_driver_sql(
            """
            INSERT INTO documents VALUES (
                'old-hash.md', 'user-1', 'old-hash.md', 'old-hash.md', 'notes.md',
                '.md', '.md', 'text/markdown', 'hash', '/tmp/old-hash.md',
                10, 'indexed', '2026-05-01', '2026-05-01', NULL
            )
            """
        )
        db.exec_driver_sql(
            """
            INSERT INTO parsed_chunks VALUES (
                'old-chunk', 'old-hash.md', 'user-1', 0, 'section',
                'hello', '{}', '2026-05-01'
            )
            """
        )
        db.exec_driver_sql(
            """
            INSERT INTO parsed_entities VALUES (
                'old-entity', 'old-hash.md', 'user-1', 'Python', 'python',
                'PROGRAMMING_LANGUAGE', 'rule', 0.9, '', '{}', '2026-05-01'
            )
            """
        )
        db.exec_driver_sql(
            """
            INSERT INTO graph_edges VALUES (
                'old-edge', 'user-1', 'python', 'fastapi', 'USES',
                'old-hash.md', 0.8, 1, '[]', '2026-05-01', '2026-05-01'
            )
            """
        )
        db.exec_driver_sql(
            """
            INSERT INTO processing_jobs VALUES (
                'old-job', 'user-1', 'old-hash.md', 'notes.md', 'SUCCESS',
                'Done', 100, '', '2026-05-01', '2026-05-01', '2026-05-01'
            )
            """
        )
        db.exec_driver_sql(
            """
            INSERT INTO processing_jobs VALUES (
                'maintenance-job', 'user-1', '', 'cleanup', 'SUCCESS',
                'Done', 100, '', '2026-05-01', '2026-05-01', '2026-05-01'
            )
            """
        )
    return engine


def test_upgrade_moves_document_references_and_adds_artifact_constraints():
    engine = _legacy_engine()

    upgrade_persistence_schema(engine)
    upgrade_persistence_schema(engine)  # the startup path must be repeatable

    with engine.connect() as db:
        document_id = db.scalar(text("SELECT id FROM documents"))
        assert len(document_id) == 32
        assert document_id != "old-hash.md"
        assert db.scalar(text("SELECT document_id FROM parsed_chunks")) == document_id
        assert db.scalar(text("SELECT document_id FROM parsed_entities")) == document_id
        assert db.scalar(text("SELECT source_document_id FROM graph_edges")) == document_id
        assert db.scalar(text("SELECT document_id FROM processing_jobs WHERE job_id = 'old-job'")) == document_id
        assert db.scalar(text("SELECT document_id FROM processing_jobs WHERE job_id = 'maintenance-job'")) is None
        assert db.scalar(text("SELECT workspace_id FROM documents")) == default_workspace_id("user-1")
        assert db.scalar(text("SELECT workspace_id FROM parsed_chunks")) == default_workspace_id("user-1")
        assert db.scalar(text("SELECT workspace_id FROM parsed_entities")) == default_workspace_id("user-1")
        assert db.scalar(text("SELECT workspace_id FROM graph_edges")) == default_workspace_id("user-1")
        assert db.scalar(text("SELECT workspace_id FROM processing_jobs WHERE job_id = 'old-job'")) == default_workspace_id("user-1")
        assert db.scalar(text("SELECT id FROM workspaces WHERE user_id = 'user-1'")) == default_workspace_id("user-1")

    inspector = inspect(engine)
    assert {"medical_document_profiles", "document_sections"}.issubset(
        set(inspector.get_table_names())
    )
    chunk_uniques = [item["column_names"] for item in inspector.get_unique_constraints("parsed_chunks")]
    entity_uniques = [item["column_names"] for item in inspector.get_unique_constraints("parsed_entities")]
    assert ["user_id", "workspace_id", "document_id", "chunk_index"] in chunk_uniques
    assert ["user_id", "workspace_id", "document_id", "normalized", "label"] in entity_uniques
    assert inspector.get_foreign_keys("parsed_chunks")[0]["referred_table"] == "documents"
    assert inspector.get_foreign_keys("parsed_entities")[0]["referred_table"] == "documents"
    assert inspector.get_foreign_keys("graph_edges")[0]["referred_table"] == "documents"
    assert inspector.get_foreign_keys("processing_jobs")[0]["referred_table"] == "documents"


def test_backfill_keeps_children_in_the_document_workspace_after_repeat():
    """A rerun must repair child rows that were given the wrong fallback workspace."""
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)

    user_id = "user-1"
    workspace_id = "research-workspace"
    document_id = uuid.uuid4().hex
    fallback_workspace_id = default_workspace_id(user_id)

    with Session(engine) as db:
        db.add_all(
            [
                UserRecord(
                    id=user_id,
                    email="user-1@example.com",
                    name="User One",
                    hashed_password="test-hash",
                ),
                WorkspaceRecord(
                    id=workspace_id,
                    user_id=user_id,
                    name="Cancer research",
                    research_question="How does this paper describe the treatment?",
                    domain="medical",
                    status="active",
                ),
                DocumentRecord(
                    id=document_id,
                    user_id=user_id,
                    workspace_id=workspace_id,
                    filename="paper.pdf",
                    stored_filename="paper.pdf",
                    original_filename="paper.pdf",
                    file_extension=".pdf",
                    file_type=".pdf",
                    mime_type="application/pdf",
                    file_hash="paper-hash",
                    file_path="/tmp/paper.pdf",
                    file_size=100,
                    status="indexed",
                ),
                ParsedChunkRecord(
                    id="chunk-1",
                    document_id=document_id,
                    user_id=user_id,
                    workspace_id=None,
                    chunk_index=0,
                    chunk_type="page",
                    text="A paper chunk",
                    metadata_json="{}",
                ),
                ParsedEntityRecord(
                    id="entity-1",
                    document_id=document_id,
                    user_id=user_id,
                    workspace_id=fallback_workspace_id,
                    text="Treatment",
                    normalized="treatment",
                    label="CONCEPT",
                    source="rule",
                    confidence=0.9,
                    context="",
                    metadata_json="{}",
                ),
                GraphEdgeRecord(
                    id="edge-1",
                    user_id=user_id,
                    workspace_id=None,
                    source_node_id="treatment",
                    target_node_id="outcome",
                    relation_type="RELATED_TO",
                    source_document_id=document_id,
                    confidence=0.6,
                    weight=1,
                    sources_json="[]",
                ),
                ProcessingJobRecord(
                    job_id="job-1",
                    user_id=user_id,
                    workspace_id=fallback_workspace_id,
                    document_id=document_id,
                    original_filename="paper.pdf",
                    status="SUCCESS",
                    step="Done",
                    progress=100,
                    error="",
                ),
            ]
        )
        db.commit()

    upgrade_persistence_schema(engine)
    upgrade_persistence_schema(engine)

    with engine.connect() as db:
        for table in (
            "parsed_chunks",
            "parsed_entities",
            "graph_edges",
            "processing_jobs",
        ):
            assert db.scalar(
                text(f"SELECT workspace_id FROM {table} LIMIT 1")
            ) == workspace_id

    engine.dispose()


def _postgres_test_url() -> str | None:
    """Use an explicit test URL so the local application database is untouched."""
    return (
        os.getenv("GRAPHMIND_TEST_POSTGRES_URL")
        or os.getenv("TEST_POSTGRES_URL")
        or os.getenv("POSTGRES_TEST_DATABASE_URL")
    )


def _create_postgres_legacy_schema(engine) -> None:
    """Create the pre-migration shape used by the PostgreSQL upgrade test."""
    with engine.begin() as db:
        db.exec_driver_sql(
            """
            CREATE TABLE documents (
                id VARCHAR(255) PRIMARY KEY,
                user_id VARCHAR(64) NOT NULL,
                file_hash VARCHAR(64) NOT NULL
            )
            """
        )
        db.exec_driver_sql(
            """
            CREATE TABLE parsed_chunks (
                id VARCHAR(320) PRIMARY KEY,
                document_id VARCHAR(255) NOT NULL,
                user_id VARCHAR(64) NOT NULL,
                chunk_index INTEGER NOT NULL,
                UNIQUE (document_id, chunk_index)
            )
            """
        )
        db.exec_driver_sql(
            """
            CREATE TABLE parsed_entities (
                id VARCHAR(320) PRIMARY KEY,
                document_id VARCHAR(255) NOT NULL,
                user_id VARCHAR(64) NOT NULL,
                normalized VARCHAR(255) NOT NULL,
                label VARCHAR(80) NOT NULL,
                UNIQUE (document_id, normalized, label)
            )
            """
        )
        db.exec_driver_sql(
            """
            CREATE TABLE graph_edges (
                id VARCHAR(320) PRIMARY KEY,
                user_id VARCHAR(64) NOT NULL,
                source_node_id VARCHAR(255) NOT NULL,
                target_node_id VARCHAR(255) NOT NULL,
                relation_type VARCHAR(80) NOT NULL,
                source_document_id VARCHAR(255) NOT NULL
            )
            """
        )
        db.exec_driver_sql(
            """
            CREATE TABLE processing_jobs (
                job_id VARCHAR(255) PRIMARY KEY,
                user_id VARCHAR(64) NOT NULL,
                document_id VARCHAR(255) NOT NULL,
                original_filename VARCHAR(255) NOT NULL,
                status VARCHAR(32) NOT NULL,
                step VARCHAR(255) NOT NULL,
                progress INTEGER NOT NULL,
                error TEXT NOT NULL,
                created_at TIMESTAMP NOT NULL,
                updated_at TIMESTAMP NOT NULL,
                finished_at TIMESTAMP
            )
            """
        )

        db.execute(
            text("INSERT INTO documents (id, user_id, file_hash) VALUES (:id, :user, :hash)"),
            {"id": "legacy-doc", "user": "user-1", "hash": "legacy-hash"},
        )
        db.execute(
            text(
                "INSERT INTO parsed_chunks (id, document_id, user_id, chunk_index) "
                "VALUES (:id, :document, :user, :index)"
            ),
            [
                {"id": "valid-chunk", "document": "legacy-doc", "user": "user-1", "index": 0},
                {"id": "orphan-chunk", "document": "missing-doc", "user": "user-1", "index": 1},
            ],
        )
        db.execute(
            text(
                "INSERT INTO parsed_entities (id, document_id, user_id, normalized, label) "
                "VALUES (:id, :document, :user, :normalized, :label)"
            ),
            [
                {
                    "id": "valid-entity",
                    "document": "legacy-doc",
                    "user": "user-1",
                    "normalized": "python",
                    "label": "LANGUAGE",
                },
                {
                    "id": "orphan-entity",
                    "document": "missing-doc",
                    "user": "user-1",
                    "normalized": "orphan",
                    "label": "CONCEPT",
                },
            ],
        )
        db.execute(
            text(
                "INSERT INTO graph_edges "
                "(id, user_id, source_node_id, target_node_id, relation_type, source_document_id) "
                "VALUES (:id, :user, :source, :target, :relation, :document)"
            ),
            [
                {
                    "id": "valid-edge",
                    "user": "user-1",
                    "source": "python",
                    "target": "fastapi",
                    "relation": "USES",
                    "document": "legacy-doc",
                },
                {
                    "id": "orphan-edge",
                    "user": "user-1",
                    "source": "orphan",
                    "target": "node",
                    "relation": "USES",
                    "document": "missing-doc",
                },
            ],
        )
        db.execute(
            text(
                "INSERT INTO processing_jobs "
                "(job_id, user_id, document_id, original_filename, status, step, progress, error, "
                "created_at, updated_at, finished_at) "
                "VALUES (:job, :user, :document, :filename, 'SUCCESS', 'Done', 100, '', now(), now(), now())"
            ),
            [
                {
                    "job": "valid-job",
                    "user": "user-1",
                    "document": "legacy-doc",
                    "filename": "notes.md",
                },
                {
                    "job": "empty-job",
                    "user": "user-1",
                    "document": "",
                    "filename": "cleanup",
                },
                {
                    "job": "orphan-job",
                    "user": "user-1",
                    "document": "missing-doc",
                    "filename": "orphan.md",
                },
            ],
        )


def test_upgrade_cleans_legacy_postgres_references():
    """Verify old PostgreSQL rows can migrate and honor SET NULL on deletion."""
    url = _postgres_test_url()
    if not url or not url.startswith("postgresql"):
        pytest.skip("set GRAPHMIND_TEST_POSTGRES_URL to run the PostgreSQL migration test")

    admin_engine = create_engine(url, future=True)
    schema = f"graphmind_migration_{uuid.uuid4().hex[:12]}"
    with admin_engine.begin() as db:
        db.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    admin_engine.dispose()

    engine = create_engine(
        url,
        future=True,
        poolclass=NullPool,
        connect_args={"options": f"-csearch_path={schema}"},
    )
    cleanup_engine = create_engine(url, future=True)
    try:
        _create_postgres_legacy_schema(engine)
        upgrade_persistence_schema(engine)
        upgrade_persistence_schema(engine)

        with engine.connect() as db:
            document_id = db.scalar(text("SELECT id FROM documents"))
            assert len(document_id) == 32
            assert db.scalar(
                text("SELECT document_id FROM processing_jobs WHERE job_id = 'valid-job'")
            ) == document_id
            assert db.scalar(
                text("SELECT document_id FROM processing_jobs WHERE job_id = 'empty-job'")
            ) is None
            assert db.scalar(
                text("SELECT document_id FROM processing_jobs WHERE job_id = 'orphan-job'")
            ) is None
            assert db.scalar(text("SELECT COUNT(*) FROM parsed_chunks")) == 1
            assert db.scalar(text("SELECT COUNT(*) FROM parsed_entities")) == 1
            assert db.scalar(text("SELECT COUNT(*) FROM graph_edges")) == 1

        job_column = next(
            column
            for column in inspect(engine).get_columns("processing_jobs")
            if column["name"] == "document_id"
        )
        assert job_column["nullable"] is True

        job_fk = next(
            foreign_key
            for foreign_key in inspect(engine).get_foreign_keys("processing_jobs")
            if foreign_key["referred_table"] == "documents"
        )
        assert (job_fk.get("options") or {}).get("ondelete") == "SET NULL"

        with engine.begin() as db:
            db.execute(text("DELETE FROM documents WHERE id = :id"), {"id": document_id})
        with engine.connect() as db:
            assert db.scalar(
                text("SELECT document_id FROM processing_jobs WHERE job_id = 'valid-job'")
            ) is None
    finally:
        engine.dispose()
        with cleanup_engine.begin() as db:
            db.exec_driver_sql(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        cleanup_engine.dispose()
