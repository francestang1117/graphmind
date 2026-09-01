"""Small, repeatable upgrades for databases created by older GraphMind builds."""

from __future__ import annotations

import json
import logging
import uuid

from sqlalchemy import bindparam, inspect, text

log = logging.getLogger(__name__)


def upgrade_persistence_schema(engine) -> None:
    """Bring the document/artifact tables up to the current ownership model."""
    if engine.dialect.name == "sqlite":
        with engine.begin() as connection:
            changed = _move_legacy_document_ids(connection)
            rebuilt = 0
            for table, columns, constraint in (
                (
                    "parsed_chunks",
                    ("user_id", "document_id", "chunk_index"),
                    "fk_parsed_chunks_document",
                ),
                (
                    "parsed_entities",
                    ("user_id", "document_id", "normalized", "label"),
                    "fk_parsed_entities_document",
                ),
            ):
                if _needs_sqlite_rebuild(connection, table, columns):
                    _rebuild_sqlite_artifact_table(connection, table, constraint)
                    rebuilt += 1

            for table, column, constraint, nullable in (
                (
                    "graph_edges",
                    "source_document_id",
                    "fk_graph_edges_document",
                    False,
                ),
                (
                    "processing_jobs",
                    "document_id",
                    "fk_processing_jobs_document",
                    True,
                ),
            ):
                if _needs_sqlite_document_fk(connection, table, column, nullable):
                    _rebuild_sqlite_reference_table(connection, table, constraint, nullable)
                    rebuilt += 1

        if changed or rebuilt:
            log.info(
                "Persistence schema upgraded: %d document ids moved, %d artifact tables rebuilt",
                changed,
                rebuilt,
            )
        return

    with engine.begin() as connection:
        changed = _move_legacy_document_ids(connection)
        _ensure_server_constraints(connection)

    if changed:
        log.info("Persistence schema upgraded: %d document ids moved", changed)


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

    # These columns are the places where a document ID is stored directly.
    references = (
        ("parsed_chunks", "document_id"),
        ("parsed_entities", "document_id"),
        ("graph_edges", "source_document_id"),
        ("processing_jobs", "document_id"),
    )
    for old_id, new_id in replacements.items():
        for table, column in references:
            if _has_table(connection, table):
                old_values = [old_id]
                if table == "graph_edges":
                    # Older graph rows used the in-memory node prefix. Keep
                    # those rows attached when the document ID is upgraded.
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
    if not _has_table(connection, "graph_nodes"):
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
                    "UPDATE graph_nodes "
                    "SET source_document_ids_json = :sources "
                    "WHERE id = :row_id"
                ),
                {"row_id": row_id, "sources": json.dumps(updated, ensure_ascii=False)},
            )


def _needs_sqlite_rebuild(connection, table: str, unique_columns: tuple[str, ...]) -> bool:
    if not _has_table(connection, table):
        return False

    inspector = inspect(connection)
    has_unique = any(
        tuple(item.get("column_names") or ()) == unique_columns
        for item in inspector.get_unique_constraints(table)
    )
    has_document_fk = any(
        item.get("referred_table") == "documents"
        and item.get("constrained_columns") == ["document_id"]
        for item in inspector.get_foreign_keys(table)
    )
    return not (has_unique and has_document_fk)


def _needs_sqlite_document_fk(
    connection,
    table: str,
    column: str,
    nullable: bool,
) -> bool:
    if not _has_table(connection, table):
        return False

    inspector = inspect(connection)
    has_fk = any(
        item.get("referred_table") == "documents"
        and item.get("constrained_columns") == [column]
        for item in inspector.get_foreign_keys(table)
    )
    column_info = next(
        (item for item in inspector.get_columns(table) if item.get("name") == column),
        None,
    )
    has_expected_nullability = not nullable or bool(column_info and column_info.get("nullable"))
    return not (has_fk and has_expected_nullability)


def _rebuild_sqlite_artifact_table(connection, table: str, foreign_key_name: str) -> None:
    """SQLite cannot alter a table constraint, so copy the rows once."""
    backup = f"_graphmind_legacy_{table}"
    if _has_table(connection, backup):
        raise RuntimeError(f"Previous migration left an unfinished table: {backup}")

    _drop_sqlite_indexes(connection, table)

    connection.exec_driver_sql(f"ALTER TABLE {table} RENAME TO {backup}")
    if table == "parsed_chunks":
        connection.exec_driver_sql(
            f"""
            CREATE TABLE {table} (
                id VARCHAR(320) NOT NULL,
                document_id VARCHAR(255) NOT NULL,
                user_id VARCHAR(64) NOT NULL,
                chunk_index INTEGER NOT NULL,
                chunk_type VARCHAR(64) NOT NULL,
                text TEXT NOT NULL,
                metadata_json TEXT NOT NULL,
                created_at DATETIME NOT NULL,
                PRIMARY KEY (id),
                CONSTRAINT uq_chunks_user_document_index
                    UNIQUE (user_id, document_id, chunk_index),
                CONSTRAINT {foreign_key_name}
                    FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE
            )
            """
        )
        columns = "id, document_id, user_id, chunk_index, chunk_type, text, metadata_json, created_at"
    else:
        connection.exec_driver_sql(
            f"""
            CREATE TABLE {table} (
                id VARCHAR(320) NOT NULL,
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
                PRIMARY KEY (id),
                CONSTRAINT uq_entities_user_document_name_label
                    UNIQUE (user_id, document_id, normalized, label),
                CONSTRAINT {foreign_key_name}
                    FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE
            )
            """
        )
        columns = "id, document_id, user_id, text, normalized, label, source, confidence, context, metadata_json, created_at"

    connection.exec_driver_sql(
        f"INSERT INTO {table} ({columns}) SELECT {columns} FROM {backup}"
    )
    connection.exec_driver_sql(f"DROP TABLE {backup}")
    connection.exec_driver_sql(f"CREATE INDEX ix_{table}_user_id ON {table} (user_id)")
    connection.exec_driver_sql(f"CREATE INDEX ix_{table}_document_id ON {table} (document_id)")


def _rebuild_sqlite_reference_table(
    connection,
    table: str,
    foreign_key_name: str,
    nullable_document_id: bool,
) -> None:
    """Add document ownership to old graph/job tables without losing rows."""
    backup = f"_graphmind_legacy_{table}"
    if _has_table(connection, backup):
        raise RuntimeError(f"Previous migration left an unfinished table: {backup}")

    _drop_sqlite_indexes(connection, table)
    connection.exec_driver_sql(f"ALTER TABLE {table} RENAME TO {backup}")

    if table == "graph_edges":
        connection.exec_driver_sql(
            f"""
            CREATE TABLE {table} (
                id VARCHAR(320) NOT NULL,
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
                PRIMARY KEY (id),
                CONSTRAINT uq_graph_edges_user_relation_doc
                    UNIQUE (user_id, source_node_id, target_node_id, relation_type, source_document_id),
                CONSTRAINT {foreign_key_name}
                    FOREIGN KEY (source_document_id) REFERENCES documents(id) ON DELETE CASCADE
            )
            """
        )
        columns = (
            "id, user_id, source_node_id, target_node_id, relation_type, "
            "source_document_id, confidence, weight, sources_json, created_at, updated_at"
        )
        orphan_count = connection.execute(
            text(
                f"DELETE FROM {backup} "
                "WHERE source_document_id NOT IN (SELECT id FROM documents)"
            )
        ).rowcount or 0
        if orphan_count:
            log.warning("Dropped %d graph edges with no source document", orphan_count)
        connection.exec_driver_sql(
            f"INSERT INTO {table} ({columns}) SELECT {columns} FROM {backup}"
        )
        indexes = (
            ("user_id", "user_id"),
            ("source_node_id", "source_node_id"),
            ("target_node_id", "target_node_id"),
            ("relation_type", "relation_type"),
            ("source_document_id", "source_document_id"),
        )
    else:
        connection.exec_driver_sql(
            f"""
            CREATE TABLE {table} (
                job_id VARCHAR(255) NOT NULL,
                user_id VARCHAR(64) NOT NULL,
                document_id VARCHAR(255),
                original_filename VARCHAR(255) NOT NULL,
                status VARCHAR(32) NOT NULL,
                step VARCHAR(255) NOT NULL,
                progress INTEGER NOT NULL,
                error TEXT NOT NULL,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                finished_at DATETIME,
                PRIMARY KEY (job_id),
                CONSTRAINT {foreign_key_name}
                    FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE SET NULL
            )
            """
        )
        columns = (
            "job_id, user_id, document_id, original_filename, status, step, "
            "progress, error, created_at, updated_at, finished_at"
        )
        connection.exec_driver_sql(
            f"""
            INSERT INTO {table} ({columns})
            SELECT job_id, user_id,
                   CASE WHEN document_id IN (SELECT id FROM documents)
                        THEN document_id ELSE NULL END,
                   original_filename, status, step, progress, error,
                   created_at, updated_at, finished_at
            FROM {backup}
            """
        )
        indexes = (
            ("user_id", "user_id"),
            ("document_id", "document_id"),
            ("status", "status"),
        )

    connection.exec_driver_sql(f"DROP TABLE {backup}")
    for suffix, column in indexes:
        connection.exec_driver_sql(
            f"CREATE INDEX ix_{table}_{suffix} ON {table} ({column})"
        )


def _drop_sqlite_indexes(connection, table: str) -> None:
    # SQLite keeps index names when a table is renamed, so remove them first.
    for index in inspect(connection).get_indexes(table):
        connection.exec_driver_sql(f"DROP INDEX IF EXISTS {index['name']}")


def _ensure_server_constraints(connection) -> None:
    """Add constraints on PostgreSQL without using SQLite's table-copy path."""
    _ensure_unique_constraint(
        connection,
        "documents",
        "uq_documents_user_hash",
        ("user_id", "file_hash"),
        old_names=(),
    )
    _ensure_unique_constraint(
        connection,
        "parsed_chunks",
        "uq_chunks_user_document_index",
        ("user_id", "document_id", "chunk_index"),
        old_names=("uq_chunks_document_index",),
    )
    _ensure_unique_constraint(
        connection,
        "parsed_entities",
        "uq_entities_user_document_name_label",
        ("user_id", "document_id", "normalized", "label"),
        old_names=("uq_entities_document_name_label",),
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


def _ensure_unique_constraint(
    connection,
    table: str,
    name: str,
    columns: tuple[str, ...],
    old_names: tuple[str, ...],
) -> None:
    if not _has_table(connection, table):
        return
    inspector = inspect(connection)
    if any(
        tuple(item.get("column_names") or ()) == columns
        for item in inspector.get_unique_constraints(table)
    ):
        return

    for old_name in old_names:
        connection.execute(text(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {old_name}"))
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
    if not _has_table(connection, table):
        return
    inspector = inspect(connection)
    if any(
        item.get("referred_table") == "documents"
        and item.get("constrained_columns") == [column]
        for item in inspector.get_foreign_keys(table)
    ):
        return

    connection.execute(
        text(
            f"ALTER TABLE {table} ADD CONSTRAINT {name} "
            f"FOREIGN KEY ({column}) REFERENCES documents(id) ON DELETE {ondelete}"
        )
    )


def _has_table(connection, table: str) -> bool:
    return inspect(connection).has_table(table)


def _is_uuid(value: str) -> bool:
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError, TypeError):
        return False
    return parsed.hex == value.replace("-", "").lower()
