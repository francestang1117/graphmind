"""Regression checks for upgrading the old hash-keyed SQLite schema."""

from sqlalchemy import create_engine, inspect, text

from app.core.database_migrations import upgrade_persistence_schema


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

    inspector = inspect(engine)
    chunk_uniques = [item["column_names"] for item in inspector.get_unique_constraints("parsed_chunks")]
    entity_uniques = [item["column_names"] for item in inspector.get_unique_constraints("parsed_entities")]
    assert ["user_id", "document_id", "chunk_index"] in chunk_uniques
    assert ["user_id", "document_id", "normalized", "label"] in entity_uniques
    assert inspector.get_foreign_keys("parsed_chunks")[0]["referred_table"] == "documents"
    assert inspector.get_foreign_keys("parsed_entities")[0]["referred_table"] == "documents"
    assert inspector.get_foreign_keys("graph_edges")[0]["referred_table"] == "documents"
    assert inspector.get_foreign_keys("processing_jobs")[0]["referred_table"] == "documents"
