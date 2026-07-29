"""Schema bootstrap and versioned migrations."""

from __future__ import annotations

from pathlib import Path

import duckdb

from database.connection import get_connection
from utils.config import SCHEMA_VERSION

SCHEMA_PATH = Path(__file__).with_name("schema.sql")

# Historical import mapped Finale - Top Seed / Consolation / Runner-up → rounds 7 / 8 / 9.
_LEGACY_FINALE_ROUND_LABELS = {
    7: "Top Seed",
    8: "Consolation",
    9: "Runner-up",
}


def _split_sql(sql: str) -> list[str]:
    """Split SQL file into statements (simple ; splitter, ignores empty)."""
    parts: list[str] = []
    buf: list[str] = []
    for line in sql.splitlines():
        stripped = line.strip()
        if stripped.startswith("--"):
            continue
        buf.append(line)
        if stripped.endswith(";"):
            stmt = "\n".join(buf).strip()
            if stmt:
                parts.append(stmt)
            buf = []
    tail = "\n".join(buf).strip()
    if tail:
        parts.append(tail)
    return parts


def _get_schema_version(conn: duckdb.DuckDBPyConnection) -> int:
    try:
        row = conn.execute(
            "SELECT value FROM app_meta WHERE key = 'schema_version'"
        ).fetchone()
    except duckdb.CatalogException:
        return 0
    if row is None:
        return 0
    return int(row[0])


def _set_schema_version(conn: duckdb.DuckDBPyConnection, version: int) -> None:
    conn.execute(
        """
        INSERT INTO app_meta (key, value)
        VALUES ('schema_version', ?)
        ON CONFLICT (key) DO UPDATE SET value = excluded.value
        """,
        [str(version)],
    )


def _column_names(conn: duckdb.DuckDBPyConnection, table: str) -> set[str]:
    rows = conn.execute(f"DESCRIBE {table}").fetchall()
    return {str(r[0]).lower() for r in rows}


def _add_column_if_missing(
    conn: duckdb.DuckDBPyConnection,
    table: str,
    column: str,
    ddl_type: str,
) -> None:
    if column.lower() in _column_names(conn, table):
        return
    try:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}")
    except duckdb.CatalogException as exc:
        # Concurrent page loads may race the same migration.
        # DuckDB aborts the transaction on error — roll back before continuing.
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        if "already exists" not in str(exc).lower():
            raise
        if column.lower() not in _column_names(conn, table):
            raise


def _recover_transaction(conn: duckdb.DuckDBPyConnection) -> None:
    """Clear an aborted DuckDB transaction so later queries can run."""
    try:
        conn.execute("SELECT 1").fetchone()
    except duckdb.TransactionException:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
    except duckdb.Error:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass


def _migrate_to_v2(conn: duckdb.DuckDBPyConnection) -> None:
    _recover_transaction(conn)
    _add_column_if_missing(conn, "matches", "is_finale", "BOOLEAN DEFAULT FALSE")
    if "is_finale" in _column_names(conn, "matches"):
        conn.execute("UPDATE matches SET is_finale = FALSE WHERE is_finale IS NULL")
    _add_column_if_missing(conn, "matches", "finale_label", "VARCHAR")

    # Collapse legacy Finale - Top Seed/Consolation/Runner-up rounds (7/8/9) into round 7.
    # (v3 later moves flagged finales to round 99.)
    events = conn.execute(
        """
        SELECT event_id
        FROM matches
        WHERE round_number IN (7, 8, 9)
        GROUP BY event_id
        HAVING
            SUM(CASE WHEN round_number = 7 THEN 1 ELSE 0 END) = 1
            AND SUM(CASE WHEN round_number = 8 THEN 1 ELSE 0 END) = 1
            AND SUM(CASE WHEN round_number = 9 THEN 1 ELSE 0 END) = 1
            AND MAX(round_number) = 9
        """
    ).fetchall()
    for (event_id,) in events:
        for legacy_round, label in _LEGACY_FINALE_ROUND_LABELS.items():
            conn.execute(
                """
                UPDATE matches
                SET is_finale = TRUE,
                    finale_label = ?,
                    round_number = 7
                WHERE event_id = ? AND round_number = ?
                """,
                [label, int(event_id), int(legacy_round)],
            )


def _migrate_to_v3(conn: duckdb.DuckDBPyConnection) -> None:
    """Move finale matches onto dedicated round 99."""
    from models.match import FINALE_ROUND

    _recover_transaction(conn)
    if "is_finale" not in _column_names(conn, "matches"):
        return
    conn.execute(
        """
        UPDATE matches
        SET round_number = ?
        WHERE COALESCE(is_finale, FALSE) = TRUE
          AND round_number <> ?
        """,
        [FINALE_ROUND, FINALE_ROUND],
    )


def apply_schema(conn: duckdb.DuckDBPyConnection | None = None) -> int:
    """Apply base schema if needed. Returns current schema version."""
    conn = conn or get_connection()
    _recover_transaction(conn)
    current = _get_schema_version(conn)

    if current == 0:
        sql = SCHEMA_PATH.read_text(encoding="utf-8")
        for stmt in _split_sql(sql):
            conn.execute(stmt)
        _set_schema_version(conn, SCHEMA_VERSION)
        return SCHEMA_VERSION

    if current < 2:
        _migrate_to_v2(conn)
        _set_schema_version(conn, 2)

    if _get_schema_version(conn) < 3:
        _migrate_to_v3(conn)
        _set_schema_version(conn, 3)

    current = _get_schema_version(conn)
    if current < SCHEMA_VERSION:
        _set_schema_version(conn, SCHEMA_VERSION)

    return _get_schema_version(conn)


def init_db(db_path: str | None = None) -> duckdb.DuckDBPyConnection:
    """Ensure DB file exists and schema is applied."""
    conn = get_connection(db_path)
    _recover_transaction(conn)
    apply_schema(conn)
    return conn
