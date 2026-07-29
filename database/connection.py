"""DuckDB connection management."""

from __future__ import annotations

from pathlib import Path

import duckdb

from utils.config import DATA_DIR, DEFAULT_DB_PATH

_connection: duckdb.DuckDBPyConnection | None = None
_connection_path: str | None = None


def get_connection(db_path: str | Path | None = None) -> duckdb.DuckDBPyConnection:
    """Return a process-wide DuckDB connection, creating the file if needed."""
    global _connection, _connection_path

    path = Path(db_path) if db_path else DEFAULT_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path_str = str(path.resolve())

    # Reuse healthy connection
    if _connection is not None and (_connection_path == path_str or db_path is None):
        if _connection_path == path_str and _connection_is_healthy(_connection):
            return _connection
        # Stale / aborted connection — reopen
        close_connection()

    _connection = duckdb.connect(path_str)
    _connection_path = path_str
    return _connection


def _connection_is_healthy(conn: duckdb.DuckDBPyConnection) -> bool:
    try:
        row = conn.execute("SELECT 1").fetchone()
        return bool(row) and int(row[0]) == 1
    except Exception:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        # Re-check after rollback
        try:
            row = conn.execute("SELECT 1").fetchone()
            return bool(row) and int(row[0]) == 1
        except Exception:
            return False


def close_connection() -> None:
    global _connection, _connection_path
    if _connection is not None:
        try:
            _connection.close()
        except Exception:
            pass
        _connection = None
        _connection_path = None


def reset_connection(db_path: str | Path | None = None) -> duckdb.DuckDBPyConnection:
    """Force-close and reopen the process connection."""
    path = Path(db_path) if db_path else (_connection_path or DEFAULT_DB_PATH)
    close_connection()
    return get_connection(path)


def ensure_data_dir() -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR
