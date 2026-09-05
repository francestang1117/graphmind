"""Compatibility migrations for the persistence tables.

The project used hash-based document ids and did not have research projects
at first. The migration keeps those local databases usable while moving rows
into the current workspace-aware schema.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import bindparam, inspect, text

from app.core.workspace import (
    DEFAULT_WORKSPACE_DOMAIN,
    DEFAULT_WORKSPACE_NAME,
    DEFAULT_WORKSPACE_STATUS,
    default_workspace_id,
)

log = logging.getLogger(__name__)


_WORKSPACE_TABLES = (
    "documents",
    "parsed_chunks",
    "parsed_entities",
    "graph_nodes",
    "graph_edges",
    "processing_jobs",
    "medical_document_profiles",
    "document_sections",
)


def upgrade_persistence_schema(engine) -> None:
    """Apply the workspace migration without touching application data."""
    if engine.dialect.name == "sqlite":
        _upgrade_sqlite(engine)
        return

    with engine.begin() as connection:
        _ensure_workspace_table(connection)
        _ensure_medical_document_columns(connection)
        _ensure_medical_tables(connection)
        _ensure_workspace_columns(connection)
        changed = _move_legacy_document_ids(connection)
        seeded = _seed_default_workspaces(connection)
        backfilled = _backfill_workspace_ids(connection)
        _ensure_server_constraints(connection)

    if changed or seeded or backfilled:
        log.info(
            "Persistence schema upgraded: %d document ids moved, "
            "%d default workspaces added, %d rows assigned",
            changed,
            seeded,
            backfilled,
        )


def _upgrade_sqlite(engine) -> None:
    """SQLite needs table copies for new unique constraints and foreign keys."""
    # SQLite cannot toggle foreign-key enforcement in an open transaction.
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        connection.commit()
        try:
            with connection.begin():
                _ensure_workspace_table(connection)
                _ensure_medical_document_columns(connection)
                _ensure_medical_tables(connection)
                _ensure_workspace_columns(connection)
                changed = _move_legacy_document_ids(connection)
                seeded = _seed_default_workspaces(connection)
                backfilled = _backfill_workspace_ids(connection)
                _clean_sqlite_orphans(connection)

                rebuilt = 0
                rebuild_checks = (
                    ("documents", _needs_sqlite_documents_rebuild),
                    ("parsed_chunks", _needs_sqlite_chunks_rebuild),
                    ("parsed_entities", _needs_sqlite_entities_rebuild),
                    ("graph_nodes", _needs_sqlite_nodes_rebuild),
                    ("graph_edges", _needs_sqlite_edges_rebuild),
                    ("processing_jobs", _needs_sqlite_jobs_rebuild),
                    ("medical_document_profiles", _needs_sqlite_profile_rebuild),
                    ("document_sections", _needs_sqlite_sections_rebuild),
                )
                for table, needs_rebuild in rebuild_checks:
                    if needs_rebuild(connection):
                        _rebuild_sqlite_table(connection, table)
                        rebuilt += 1
        finally:
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            connection.commit()

    if changed or seeded or backfilled or rebuilt:
        log.info(
            "Persistence schema upgraded: %d document ids moved, "
            "%d default workspaces added, %d rows assigned, %d tables rebuilt",
            changed,
            seeded,
            backfilled,
            rebuilt,
        )


def _ensure_workspace_table(connection) -> None:
    if _has_table(connection, "workspaces"):
        return

    timestamp_type = (
        "DATETIME"
        if connection.dialect.name == "sqlite"
        else "TIMESTAMP WITH TIME ZONE"
    )
    connection.exec_driver_sql(
        f"""
        CREATE TABLE workspaces (
            id VARCHAR(64) NOT NULL PRIMARY KEY,
            user_id VARCHAR(64) NOT NULL,
            name VARCHAR(160) NOT NULL,
            research_question TEXT NOT NULL,
            domain VARCHAR(64) NOT NULL,
            status VARCHAR(32) NOT NULL,
            created_at {timestamp_type} NOT NULL,
            updated_at {timestamp_type} NOT NULL
        )
        """
    )
    for name, column in (
        ("ix_workspaces_user_id", "user_id"),
        ("ix_workspaces_domain", "domain"),
        ("ix_workspaces_status", "status"),
    ):
        connection.exec_driver_sql(
            f"CREATE INDEX IF NOT EXISTS {name} ON workspaces ({column})"
        )


def _ensure_medical_document_columns(connection) -> None:
    """Add the small amount of medical metadata kept on each document."""
    if not _has_table(connection, "documents"):
        return

    columns = (
        ("document_kind", "VARCHAR(64)"),
        ("source_kind", "VARCHAR(64)"),
        ("language", "VARCHAR(16)"),
        ("document_date", "VARCHAR(32)"),
        ("parser_version", "VARCHAR(64)"),
    )
    for column, column_type in columns:
        if _has_column(connection, "documents", column):
            continue
        connection.exec_driver_sql(
            f"ALTER TABLE documents ADD COLUMN {column} {column_type}"
        )

    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_documents_document_kind "
        "ON documents (document_kind)"
    )


def _ensure_medical_tables(connection) -> None:
    """Create the profile and section tables for older databases."""
    if not _has_table(connection, "documents"):
        return

    timestamp_type = (
        "DATETIME"
        if connection.dialect.name == "sqlite"
        else "TIMESTAMP WITH TIME ZONE"
    )
    if not _has_table(connection, "medical_document_profiles"):
        connection.exec_driver_sql(
            f"""
            CREATE TABLE medical_document_profiles (
                id VARCHAR(320) NOT NULL PRIMARY KEY,
                user_id VARCHAR(64) NOT NULL,
                workspace_id VARCHAR(64),
                document_id VARCHAR(255) NOT NULL,
                document_kind VARCHAR(64) NOT NULL,
                language VARCHAR(16) NOT NULL,
                confidence FLOAT NOT NULL,
                classifier_version VARCHAR(64) NOT NULL,
                signals_json TEXT NOT NULL,
                warnings_json TEXT NOT NULL,
                missing_sections_json TEXT NOT NULL,
                created_at {timestamp_type} NOT NULL,
                updated_at {timestamp_type} NOT NULL,
                CONSTRAINT uq_medical_profiles_user_workspace_document
                    UNIQUE (user_id, workspace_id, document_id),
                CONSTRAINT fk_medical_profiles_document
                    FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE
            )
            """
        )

    if not _has_table(connection, "document_sections"):
        connection.exec_driver_sql(
            f"""
            CREATE TABLE document_sections (
                id VARCHAR(320) NOT NULL PRIMARY KEY,
                user_id VARCHAR(64) NOT NULL,
                workspace_id VARCHAR(64),
                document_id VARCHAR(255) NOT NULL,
                section_type VARCHAR(64) NOT NULL,
                original_title VARCHAR(255) NOT NULL,
                ordinal INTEGER NOT NULL,
                page_start INTEGER,
                page_end INTEGER,
                char_start INTEGER NOT NULL,
                char_end INTEGER NOT NULL,
                text TEXT NOT NULL,
                language VARCHAR(16) NOT NULL,
                confidence FLOAT NOT NULL,
                metadata_json TEXT NOT NULL,
                created_at {timestamp_type} NOT NULL,
                CONSTRAINT uq_document_sections_user_workspace_document_ordinal
                    UNIQUE (user_id, workspace_id, document_id, ordinal),
                CONSTRAINT fk_document_sections_document
                    FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE
            )
            """
        )

    indexes = (
        ("ix_medical_document_profiles_user_id", "medical_document_profiles", "user_id"),
        ("ix_medical_document_profiles_workspace_id", "medical_document_profiles", "workspace_id"),
        ("ix_medical_document_profiles_document_id", "medical_document_profiles", "document_id"),
        ("ix_medical_document_profiles_document_kind", "medical_document_profiles", "document_kind"),
        ("ix_document_sections_user_id", "document_sections", "user_id"),
        ("ix_document_sections_workspace_id", "document_sections", "workspace_id"),
        ("ix_document_sections_document_id", "document_sections", "document_id"),
        ("ix_document_sections_section_type", "document_sections", "section_type"),
    )
    for name, table, column in indexes:
        connection.exec_driver_sql(
            f"CREATE INDEX IF NOT EXISTS {name} ON {table} ({column})"
        )


def _ensure_workspace_columns(connection) -> None:
    """Add the nullable column first; existing rows are filled below."""
    for table in _WORKSPACE_TABLES:
        if not _has_table(connection, table) or _has_column(connection, table, "workspace_id"):
            continue

        connection.exec_driver_sql(
            f"ALTER TABLE {table} ADD COLUMN workspace_id VARCHAR(64)"
        )
        connection.exec_driver_sql(
            f"CREATE INDEX IF NOT EXISTS ix_{table}_workspace_id "
            f"ON {table} (workspace_id)"
        )


def _seed_default_workspaces(connection) -> int:
    """Give users with old rows one stable compatibility workspace."""
    user_ids = _known_user_ids(connection)
    created = 0
    now = datetime.now(timezone.utc)

    for user_id in user_ids:
        workspace_id = default_workspace_id(user_id)
        if connection.dialect.name == "sqlite":
            statement = text(
                "INSERT OR IGNORE INTO workspaces "
                "(id, user_id, name, research_question, domain, status, created_at, updated_at) "
                "VALUES (:id, :user_id, :name, :question, :domain, :status, :created_at, :updated_at)"
            )
        else:
            statement = text(
                "INSERT INTO workspaces "
                "(id, user_id, name, research_question, domain, status, created_at, updated_at) "
                "VALUES (:id, :user_id, :name, :question, :domain, :status, :created_at, :updated_at) "
                "ON CONFLICT (id) DO NOTHING"
            )

        result = connection.execute(
            statement,
            {
                "id": workspace_id,
                "user_id": user_id,
                "name": DEFAULT_WORKSPACE_NAME,
                "question": "",
                "domain": DEFAULT_WORKSPACE_DOMAIN,
                "status": DEFAULT_WORKSPACE_STATUS,
                "created_at": now,
                "updated_at": now,
            },
        )
        created += result.rowcount or 0

    return created


def _known_user_ids(connection) -> set[str]:
    user_ids: set[str] = set()
    for table in ("users", *_WORKSPACE_TABLES):
        if not _has_table(connection, table) or not _has_column(connection, table, "user_id"):
            continue
        rows = connection.execute(
            text(f"SELECT DISTINCT user_id FROM {table} WHERE user_id IS NOT NULL")
        )
        user_ids.update(str(row[0]) for row in rows if row[0])
    return user_ids


def _backfill_workspace_ids(connection) -> int:
    """Attach old rows to the user's default workspace."""
    changed = 0
    user_ids = _known_user_ids(connection)

    # Documents have no parent row to copy from. Keep an existing workspace;
    # old documents without one belong in the user's compatibility workspace.
    if _has_table(connection, "documents") and _has_column(
        connection, "documents", "workspace_id"
    ):
        for user_id in user_ids:
            result = connection.execute(
                text(
                    "UPDATE documents SET workspace_id = :workspace_id "
                    "WHERE user_id = :user_id "
                    "AND (workspace_id IS NULL OR workspace_id = '')"
                ),
                {"workspace_id": default_workspace_id(user_id), "user_id": user_id},
            )
            changed += result.rowcount or 0

    # A parsed row belongs to the workspace of its document. This must happen
    # before the default fill below, and it also repairs a stale workspace id.
    for table, document_column in (
        ("parsed_chunks", "document_id"),
        ("parsed_entities", "document_id"),
        ("graph_edges", "source_document_id"),
        ("processing_jobs", "document_id"),
        ("medical_document_profiles", "document_id"),
        ("document_sections", "document_id"),
    ):
        if not _has_table(connection, table) or not _has_column(
            connection, table, document_column
        ):
            continue
        result = connection.execute(
            text(
                f"UPDATE {table} AS child SET workspace_id = "
                f"(SELECT doc.workspace_id FROM documents AS doc "
                f"WHERE doc.id = child.{document_column} "
                f"AND doc.user_id = child.user_id) "
                f"WHERE EXISTS (SELECT 1 FROM documents AS doc "
                f"WHERE doc.id = child.{document_column} "
                f"AND doc.user_id = child.user_id "
                f"AND doc.workspace_id IS NOT NULL) "
                f"AND (child.workspace_id IS NULL OR child.workspace_id = '' "
                f"OR child.workspace_id != (SELECT doc.workspace_id FROM documents AS doc "
                f"WHERE doc.id = child.{document_column} "
                f"AND doc.user_id = child.user_id))"
            )
        )
        changed += result.rowcount or 0

    # Anything left is an orphan or a legacy row without a document link.
    for table in _WORKSPACE_TABLES:
        if not _has_table(connection, table) or not _has_column(
            connection, table, "workspace_id"
        ):
            continue
        for user_id in user_ids:
            result = connection.execute(
                text(
                    f"UPDATE {table} SET workspace_id = :workspace_id "
                    "WHERE user_id = :user_id "
                    "AND (workspace_id IS NULL OR workspace_id = '')"
                ),
                {"workspace_id": default_workspace_id(user_id), "user_id": user_id},
            )
            changed += result.rowcount or 0

    return changed


def _clean_sqlite_orphans(connection) -> None:
    """Remove rows that would fail when SQLite foreign keys are restored."""
    if not _has_table(connection, "documents"):
        return

    for table, column in (
        ("parsed_chunks", "document_id"),
        ("parsed_entities", "document_id"),
        ("graph_edges", "source_document_id"),
        ("medical_document_profiles", "document_id"),
        ("document_sections", "document_id"),
    ):
        if not _has_table(connection, table) or not _has_column(connection, table, column):
            continue
        result = connection.execute(
            text(
                f"DELETE FROM {table} AS child WHERE "
                f"NULLIF(TRIM(child.{column}), '') IS NULL "
                f"OR NOT EXISTS (SELECT 1 FROM documents AS doc "
                f"WHERE doc.id = child.{column})"
            )
        )
        if result.rowcount:
            log.warning("Removed %d stale %s.%s rows", result.rowcount, table, column)

    job_column = next(
        (
            item
            for item in inspect(connection).get_columns("processing_jobs")
            if item.get("name") == "document_id"
        ),
        None,
    ) if _has_table(connection, "processing_jobs") else None
    if job_column and job_column.get("nullable"):
        result = connection.execute(
            text(
                "UPDATE processing_jobs AS job SET document_id = NULL WHERE "
                "NULLIF(TRIM(job.document_id), '') IS NULL "
                "OR NOT EXISTS (SELECT 1 FROM documents AS doc "
                "WHERE doc.id = job.document_id)"
            )
        )
        if result.rowcount:
            log.warning("Cleared %d stale processing job document links", result.rowcount)


def _move_legacy_document_ids(connection) -> int:
    """Give old hash-based document rows independent IDs and update references."""
    if not _has_table(connection, "documents"):
        return 0

    rows = connection.execute(text("SELECT id FROM documents")).all()
    replacements: dict[str, str] = {}
    used_ids = {str(row[0]) for row in rows if row[0] is not None}

    for row in rows:
        old_id = str(row[0])
        if _is_uuid(old_id):
            continue
        new_id = uuid.uuid4().hex
        while new_id in used_ids:
            new_id = uuid.uuid4().hex
        used_ids.add(new_id)
        replacements[old_id] = new_id

    if not replacements:
        return 0

    references = (
        ("parsed_chunks", "document_id"),
        ("parsed_entities", "document_id"),
        ("graph_edges", "source_document_id"),
        ("processing_jobs", "document_id"),
        ("medical_document_profiles", "document_id"),
        ("document_sections", "document_id"),
    )
    for old_id, new_id in replacements.items():
        for table, column in references:
            if not _has_table(connection, table):
                continue
            old_values = [old_id]
            if table == "graph_edges":
                old_values.append(f"doc:{old_id}")
            connection.execute(
                text(f"UPDATE {table} SET {column} = :new_id WHERE {column} IN :old_values")
                .bindparams(bindparam("old_values", expanding=True)),
                {"old_values": old_values, "new_id": new_id},
            )

        _replace_graph_node_sources(connection, old_id, new_id)
        connection.execute(
            text("UPDATE documents SET id = :new_id WHERE id = :old_id"),
            {"old_id": old_id, "new_id": new_id},
        )

    return len(replacements)


def _replace_graph_node_sources(connection, old_id: str, new_id: str) -> None:
    if not _has_table(connection, "graph_nodes") or not _has_column(
        connection, "graph_nodes", "source_document_ids_json"
    ):
        return

    rows = connection.execute(
        text("SELECT id, source_document_ids_json FROM graph_nodes")
    ).all()
    for row_id, raw_sources in rows:
        try:
            sources = json.loads(raw_sources or "[]")
        except (TypeError, json.JSONDecodeError):
            continue
        if not isinstance(sources, list):
            continue

        updated = [new_id if str(source) == old_id else source for source in sources]
        if updated != sources:
            connection.execute(
                text(
                    "UPDATE graph_nodes SET source_document_ids_json = :sources "
                    "WHERE id = :row_id"
                ),
                {"row_id": row_id, "sources": json.dumps(updated, ensure_ascii=False)},
            )


def _needs_sqlite_documents_rebuild(connection) -> bool:
    return _needs_sqlite_unique_rebuild(
        connection,
        "documents",
        ("user_id", "workspace_id", "file_hash"),
    )


def _needs_sqlite_chunks_rebuild(connection) -> bool:
    return _needs_sqlite_artifact_rebuild(
        connection,
        "parsed_chunks",
        ("user_id", "workspace_id", "document_id", "chunk_index"),
        "document_id",
    )


def _needs_sqlite_entities_rebuild(connection) -> bool:
    return _needs_sqlite_artifact_rebuild(
        connection,
        "parsed_entities",
        ("user_id", "workspace_id", "document_id", "normalized", "label"),
        "document_id",
    )


def _needs_sqlite_nodes_rebuild(connection) -> bool:
    return _needs_sqlite_unique_rebuild(
        connection,
        "graph_nodes",
        ("user_id", "workspace_id", "node_id"),
    )


def _needs_sqlite_edges_rebuild(connection) -> bool:
    return _needs_sqlite_artifact_rebuild(
        connection,
        "graph_edges",
        (
            "user_id",
            "workspace_id",
            "source_node_id",
            "target_node_id",
            "relation_type",
            "source_document_id",
        ),
        "source_document_id",
    )


def _needs_sqlite_jobs_rebuild(connection) -> bool:
    if not _has_table(connection, "processing_jobs"):
        return False
    inspector = inspect(connection)
    has_fk = any(
        item.get("referred_table") == "documents"
        and item.get("constrained_columns") == ["document_id"]
        for item in inspector.get_foreign_keys("processing_jobs")
    )
    document_column = next(
        (
            item
            for item in inspector.get_columns("processing_jobs")
            if item.get("name") == "document_id"
        ),
        None,
    )
    return not (has_fk and bool(document_column and document_column.get("nullable")))


def _needs_sqlite_profile_rebuild(connection) -> bool:
    return _needs_sqlite_artifact_rebuild(
        connection,
        "medical_document_profiles",
        ("user_id", "workspace_id", "document_id"),
        "document_id",
    )


def _needs_sqlite_sections_rebuild(connection) -> bool:
    return _needs_sqlite_artifact_rebuild(
        connection,
        "document_sections",
        ("user_id", "workspace_id", "document_id", "ordinal"),
        "document_id",
    )


def _needs_sqlite_artifact_rebuild(
    connection,
    table: str,
    unique_columns: tuple[str, ...],
    foreign_key_column: str,
) -> bool:
    return _needs_sqlite_unique_rebuild(
        connection, table, unique_columns
    ) or not _has_sqlite_document_fk(connection, table, foreign_key_column)


def _needs_sqlite_unique_rebuild(
    connection,
    table: str,
    unique_columns: tuple[str, ...],
) -> bool:
    if not _has_table(connection, table):
        return False
    inspector = inspect(connection)
    return not any(
        tuple(item.get("column_names") or ()) == unique_columns
        for item in inspector.get_unique_constraints(table)
    )


def _has_sqlite_document_fk(connection, table: str, column: str) -> bool:
    if not _has_table(connection, table):
        return False
    return any(
        item.get("referred_table") == "documents"
        and item.get("constrained_columns") == [column]
        for item in inspect(connection).get_foreign_keys(table)
    )


def _rebuild_sqlite_table(connection, table: str) -> None:
    """Copy one table into the current shape, preserving its rows."""
    backup = f"_graphmind_legacy_{table}"
    if _has_table(connection, backup):
        raise RuntimeError(f"Previous migration left an unfinished table: {backup}")

    _drop_sqlite_indexes(connection, table)
    connection.exec_driver_sql(f"ALTER TABLE {table} RENAME TO {backup}")

    ddl, columns = _sqlite_table_definition(table)
    connection.exec_driver_sql(ddl)
    connection.exec_driver_sql(
        f"INSERT INTO {table} ({columns}) SELECT {columns} FROM {backup}"
    )
    connection.exec_driver_sql(f"DROP TABLE {backup}")

    for name, column in _sqlite_indexes(table):
        connection.exec_driver_sql(
            f"CREATE INDEX IF NOT EXISTS {name} ON {table} ({column})"
        )


def _sqlite_table_definition(table: str) -> tuple[str, str]:
    definitions = {
        "documents": (
            """
            CREATE TABLE documents (
                id VARCHAR(255) NOT NULL PRIMARY KEY,
                user_id VARCHAR(64) NOT NULL,
                workspace_id VARCHAR(64),
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
                document_kind VARCHAR(64),
                source_kind VARCHAR(64),
                language VARCHAR(16),
                document_date VARCHAR(32),
                parser_version VARCHAR(64),
                created_at DATETIME NOT NULL,
                modified_at DATETIME NOT NULL,
                deleted_at DATETIME,
                CONSTRAINT uq_documents_user_workspace_hash
                    UNIQUE (user_id, workspace_id, file_hash)
            )
            """,
            "id, user_id, workspace_id, filename, stored_filename, original_filename, "
            "file_extension, file_type, mime_type, file_hash, file_path, file_size, "
            "status, document_kind, source_kind, language, document_date, parser_version, "
            "created_at, modified_at, deleted_at",
        ),
        "parsed_chunks": (
            """
            CREATE TABLE parsed_chunks (
                id VARCHAR(320) NOT NULL PRIMARY KEY,
                document_id VARCHAR(255) NOT NULL,
                user_id VARCHAR(64) NOT NULL,
                workspace_id VARCHAR(64),
                chunk_index INTEGER NOT NULL,
                chunk_type VARCHAR(64) NOT NULL,
                text TEXT NOT NULL,
                metadata_json TEXT NOT NULL,
                created_at DATETIME NOT NULL,
                CONSTRAINT uq_chunks_user_workspace_document_index
                    UNIQUE (user_id, workspace_id, document_id, chunk_index),
                CONSTRAINT fk_parsed_chunks_document
                    FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE
            )
            """,
            "id, document_id, user_id, workspace_id, chunk_index, chunk_type, text, "
            "metadata_json, created_at",
        ),
        "parsed_entities": (
            """
            CREATE TABLE parsed_entities (
                id VARCHAR(320) NOT NULL PRIMARY KEY,
                document_id VARCHAR(255) NOT NULL,
                user_id VARCHAR(64) NOT NULL,
                workspace_id VARCHAR(64),
                text VARCHAR(255) NOT NULL,
                normalized VARCHAR(255) NOT NULL,
                label VARCHAR(80) NOT NULL,
                source VARCHAR(80) NOT NULL,
                confidence FLOAT NOT NULL,
                context TEXT NOT NULL,
                metadata_json TEXT NOT NULL,
                created_at DATETIME NOT NULL,
                CONSTRAINT uq_entities_user_workspace_document_name_label
                    UNIQUE (user_id, workspace_id, document_id, normalized, label),
                CONSTRAINT fk_parsed_entities_document
                    FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE
            )
            """,
            "id, document_id, user_id, workspace_id, text, normalized, label, source, "
            "confidence, context, metadata_json, created_at",
        ),
        "graph_nodes": (
            """
            CREATE TABLE graph_nodes (
                id VARCHAR(320) NOT NULL PRIMARY KEY,
                user_id VARCHAR(64) NOT NULL,
                workspace_id VARCHAR(64),
                node_id VARCHAR(255) NOT NULL,
                label VARCHAR(255) NOT NULL,
                node_type VARCHAR(80) NOT NULL,
                confidence FLOAT NOT NULL,
                sources_json TEXT NOT NULL,
                source_document_ids_json TEXT NOT NULL,
                properties_json TEXT NOT NULL,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                CONSTRAINT uq_graph_nodes_user_workspace_node
                    UNIQUE (user_id, workspace_id, node_id)
            )
            """,
            "id, user_id, workspace_id, node_id, label, node_type, confidence, "
            "sources_json, source_document_ids_json, properties_json, created_at, updated_at",
        ),
        "graph_edges": (
            """
            CREATE TABLE graph_edges (
                id VARCHAR(320) NOT NULL PRIMARY KEY,
                user_id VARCHAR(64) NOT NULL,
                workspace_id VARCHAR(64),
                source_node_id VARCHAR(255) NOT NULL,
                target_node_id VARCHAR(255) NOT NULL,
                relation_type VARCHAR(80) NOT NULL,
                source_document_id VARCHAR(255) NOT NULL,
                confidence FLOAT NOT NULL,
                weight INTEGER NOT NULL,
                sources_json TEXT NOT NULL,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                CONSTRAINT uq_graph_edges_user_workspace_relation_doc
                    UNIQUE (user_id, workspace_id, source_node_id, target_node_id,
                            relation_type, source_document_id),
                CONSTRAINT fk_graph_edges_document
                    FOREIGN KEY (source_document_id) REFERENCES documents(id) ON DELETE CASCADE
            )
            """,
            "id, user_id, workspace_id, source_node_id, target_node_id, relation_type, "
            "source_document_id, confidence, weight, sources_json, created_at, updated_at",
        ),
        "processing_jobs": (
            """
            CREATE TABLE processing_jobs (
                job_id VARCHAR(255) NOT NULL PRIMARY KEY,
                user_id VARCHAR(64) NOT NULL,
                workspace_id VARCHAR(64),
                document_id VARCHAR(255),
                original_filename VARCHAR(255) NOT NULL,
                status VARCHAR(32) NOT NULL,
                step VARCHAR(255) NOT NULL,
                progress INTEGER NOT NULL,
                error TEXT NOT NULL,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                finished_at DATETIME,
                CONSTRAINT fk_processing_jobs_document
                    FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE SET NULL
            )
            """,
            "job_id, user_id, workspace_id, document_id, original_filename, status, step, "
            "progress, error, created_at, updated_at, finished_at",
        ),
        "medical_document_profiles": (
            """
            CREATE TABLE medical_document_profiles (
                id VARCHAR(320) NOT NULL PRIMARY KEY,
                user_id VARCHAR(64) NOT NULL,
                workspace_id VARCHAR(64),
                document_id VARCHAR(255) NOT NULL,
                document_kind VARCHAR(64) NOT NULL,
                language VARCHAR(16) NOT NULL,
                confidence FLOAT NOT NULL,
                classifier_version VARCHAR(64) NOT NULL,
                signals_json TEXT NOT NULL,
                warnings_json TEXT NOT NULL,
                missing_sections_json TEXT NOT NULL,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                CONSTRAINT uq_medical_profiles_user_workspace_document
                    UNIQUE (user_id, workspace_id, document_id),
                CONSTRAINT fk_medical_profiles_document
                    FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE
            )
            """,
            "id, user_id, workspace_id, document_id, document_kind, language, confidence, "
            "classifier_version, signals_json, warnings_json, missing_sections_json, "
            "created_at, updated_at",
        ),
        "document_sections": (
            """
            CREATE TABLE document_sections (
                id VARCHAR(320) NOT NULL PRIMARY KEY,
                user_id VARCHAR(64) NOT NULL,
                workspace_id VARCHAR(64),
                document_id VARCHAR(255) NOT NULL,
                section_type VARCHAR(64) NOT NULL,
                original_title VARCHAR(255) NOT NULL,
                ordinal INTEGER NOT NULL,
                page_start INTEGER,
                page_end INTEGER,
                char_start INTEGER NOT NULL,
                char_end INTEGER NOT NULL,
                text TEXT NOT NULL,
                language VARCHAR(16) NOT NULL,
                confidence FLOAT NOT NULL,
                metadata_json TEXT NOT NULL,
                created_at DATETIME NOT NULL,
                CONSTRAINT uq_document_sections_user_workspace_document_ordinal
                    UNIQUE (user_id, workspace_id, document_id, ordinal),
                CONSTRAINT fk_document_sections_document
                    FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE
            )
            """,
            "id, user_id, workspace_id, document_id, section_type, original_title, ordinal, "
            "page_start, page_end, char_start, char_end, text, language, confidence, "
            "metadata_json, created_at",
        ),
    }
    try:
        return definitions[table]
    except KeyError as exc:
        raise ValueError(f"No SQLite migration definition for {table}") from exc


def _sqlite_indexes(table: str) -> tuple[tuple[str, str], ...]:
    common = (
        (f"ix_{table}_user_id", "user_id"),
        (f"ix_{table}_workspace_id", "workspace_id"),
    )
    indexes = {
        "documents": common
        + (
            ("ix_documents_filename", "filename"),
            ("ix_documents_stored_filename", "stored_filename"),
            ("ix_documents_original_filename", "original_filename"),
            ("ix_documents_file_hash", "file_hash"),
            ("ix_documents_file_extension", "file_extension"),
            ("ix_documents_document_kind", "document_kind"),
            ("ix_documents_deleted_at", "deleted_at"),
        ),
        "parsed_chunks": common + (("ix_parsed_chunks_document_id", "document_id"),),
        "parsed_entities": common
        + (
            ("ix_parsed_entities_document_id", "document_id"),
            ("ix_parsed_entities_text", "text"),
            ("ix_parsed_entities_normalized", "normalized"),
            ("ix_parsed_entities_label", "label"),
        ),
        "graph_nodes": common
        + (
            ("ix_graph_nodes_node_id", "node_id"),
            ("ix_graph_nodes_label", "label"),
            ("ix_graph_nodes_node_type", "node_type"),
        ),
        "graph_edges": common
        + (
            ("ix_graph_edges_source_node_id", "source_node_id"),
            ("ix_graph_edges_target_node_id", "target_node_id"),
            ("ix_graph_edges_relation_type", "relation_type"),
            ("ix_graph_edges_source_document_id", "source_document_id"),
        ),
        "processing_jobs": common
        + (
            ("ix_processing_jobs_document_id", "document_id"),
            ("ix_processing_jobs_status", "status"),
        ),
        "medical_document_profiles": common
        + (
            ("ix_medical_document_profiles_document_id", "document_id"),
            ("ix_medical_document_profiles_document_kind", "document_kind"),
        ),
        "document_sections": common
        + (
            ("ix_document_sections_document_id", "document_id"),
            ("ix_document_sections_section_type", "section_type"),
        ),
    }
    return indexes.get(table, ())


def _ensure_server_constraints(connection) -> None:
    """Finish the PostgreSQL upgrade after columns and data are ready."""
    _ensure_processing_job_document_nullable(connection)
    _clean_orphan_document_references(connection)

    _ensure_unique_constraint(
        connection,
        "documents",
        "uq_documents_user_workspace_hash",
        ("user_id", "workspace_id", "file_hash"),
        old_names=("uq_documents_user_hash",),
    )
    _ensure_unique_constraint(
        connection,
        "parsed_chunks",
        "uq_chunks_user_workspace_document_index",
        ("user_id", "workspace_id", "document_id", "chunk_index"),
        old_names=("uq_chunks_user_document_index", "uq_chunks_document_index"),
    )
    _ensure_unique_constraint(
        connection,
        "parsed_entities",
        "uq_entities_user_workspace_document_name_label",
        ("user_id", "workspace_id", "document_id", "normalized", "label"),
        old_names=("uq_entities_user_document_name_label", "uq_entities_document_name_label"),
    )
    _ensure_unique_constraint(
        connection,
        "graph_nodes",
        "uq_graph_nodes_user_workspace_node",
        ("user_id", "workspace_id", "node_id"),
        old_names=(),
    )
    _ensure_unique_constraint(
        connection,
        "graph_edges",
        "uq_graph_edges_user_workspace_relation_doc",
        (
            "user_id",
            "workspace_id",
            "source_node_id",
            "target_node_id",
            "relation_type",
            "source_document_id",
        ),
        old_names=("uq_graph_edges_user_relation_doc",),
    )
    _ensure_unique_constraint(
        connection,
        "medical_document_profiles",
        "uq_medical_profiles_user_workspace_document",
        ("user_id", "workspace_id", "document_id"),
        old_names=(),
    )
    _ensure_unique_constraint(
        connection,
        "document_sections",
        "uq_document_sections_user_workspace_document_ordinal",
        ("user_id", "workspace_id", "document_id", "ordinal"),
        old_names=(),
    )

    _ensure_document_fk(connection, "parsed_chunks", "fk_parsed_chunks_document")
    _ensure_document_fk(connection, "parsed_entities", "fk_parsed_entities_document")
    _ensure_document_fk(connection, "graph_edges", "fk_graph_edges_document", "source_document_id")
    _ensure_document_fk(
        connection,
        "processing_jobs",
        "fk_processing_jobs_document",
        "document_id",
        ondelete="SET NULL",
    )
    _ensure_document_fk(
        connection,
        "medical_document_profiles",
        "fk_medical_profiles_document",
    )
    _ensure_document_fk(
        connection,
        "document_sections",
        "fk_document_sections_document",
    )


def _ensure_processing_job_document_nullable(connection) -> None:
    if not _has_table(connection, "processing_jobs"):
        return

    column = next(
        (
            item
            for item in inspect(connection).get_columns("processing_jobs")
            if item.get("name") == "document_id"
        ),
        None,
    )
    if column and not column.get("nullable", True):
        connection.execute(
            text(
                "ALTER TABLE processing_jobs "
                "ALTER COLUMN document_id DROP NOT NULL"
            )
        )
        log.info("Made processing_jobs.document_id nullable")


def _clean_orphan_document_references(connection) -> None:
    """Clear old child rows before PostgreSQL validates the foreign keys."""
    if not _has_table(connection, "documents"):
        return

    references = (
        ("parsed_chunks", "document_id", "delete"),
        ("parsed_entities", "document_id", "delete"),
        ("graph_edges", "source_document_id", "delete"),
        ("processing_jobs", "document_id", "null"),
        ("medical_document_profiles", "document_id", "delete"),
        ("document_sections", "document_id", "delete"),
    )
    for table, column, action in references:
        if not _has_table(connection, table) or not _has_column(connection, table, column):
            continue

        predicate = (
            f"NULLIF(BTRIM(CAST(child.{column} AS TEXT)), '') IS NULL "
            f"OR NOT EXISTS (SELECT 1 FROM documents AS doc WHERE doc.id = child.{column})"
        )
        if action == "null":
            statement = f"UPDATE {table} AS child SET {column} = NULL WHERE {predicate}"
        else:
            statement = f"DELETE FROM {table} AS child WHERE {predicate}"

        result = connection.execute(text(statement))
        if result.rowcount:
            outcome = "cleared" if action == "null" else "removed"
            log.warning("%s %d stale %s.%s references", outcome, result.rowcount, table, column)


def _ensure_unique_constraint(
    connection,
    table: str,
    name: str,
    columns: tuple[str, ...],
    old_names: tuple[str, ...],
) -> None:
    if not _has_table(connection, table):
        return

    for old_name in old_names:
        connection.execute(text(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {old_name}"))

    inspector = inspect(connection)
    if any(
        tuple(item.get("column_names") or ()) == columns
        for item in inspector.get_unique_constraints(table)
    ):
        return

    column_sql = ", ".join(columns)
    connection.execute(
        text(f"ALTER TABLE {table} ADD CONSTRAINT {name} UNIQUE ({column_sql})")
    )


def _ensure_document_fk(
    connection,
    table: str,
    name: str,
    column: str = "document_id",
    ondelete: str = "CASCADE",
) -> None:
    if not _has_table(connection, table) or not _has_column(connection, table, column):
        return

    expected_ondelete = ondelete.upper()
    inspector = inspect(connection)
    foreign_keys = inspector.get_foreign_keys(table)
    matching = []
    for foreign_key in foreign_keys:
        if (
            foreign_key.get("referred_table") != "documents"
            or foreign_key.get("constrained_columns") != [column]
        ):
            continue

        options = foreign_key.get("options") or {}
        actual_ondelete = str(options.get("ondelete") or "NO ACTION").upper()
        if actual_ondelete != expected_ondelete and foreign_key.get("name"):
            connection.execute(
                text(
                    f"ALTER TABLE {table} "
                    f"DROP CONSTRAINT IF EXISTS {foreign_key['name']}"
                )
            )
            continue
        matching.append(foreign_key)

    for foreign_key in matching:
        if foreign_key.get("name"):
            connection.execute(
                text(f"ALTER TABLE {table} VALIDATE CONSTRAINT {foreign_key['name']}")
            )
            return

    connection.execute(
        text(
            f"ALTER TABLE {table} ADD CONSTRAINT {name} "
            f"FOREIGN KEY ({column}) REFERENCES documents(id) "
            f"ON DELETE {ondelete} NOT VALID"
        )
    )
    connection.execute(text(f"ALTER TABLE {table} VALIDATE CONSTRAINT {name}"))


def _drop_sqlite_indexes(connection, table: str) -> None:
    # Explicit indexes keep their names after ALTER TABLE ... RENAME.
    for index in inspect(connection).get_indexes(table):
        connection.exec_driver_sql(f"DROP INDEX IF EXISTS {index['name']}")


def _has_table(connection, table: str) -> bool:
    return inspect(connection).has_table(table)


def _has_column(connection, table: str, column: str) -> bool:
    return any(item.get("name") == column for item in inspect(connection).get_columns(table))


def _is_uuid(value: str) -> bool:
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError, TypeError):
        return False
    return parsed.hex == value.replace("-", "").lower()
