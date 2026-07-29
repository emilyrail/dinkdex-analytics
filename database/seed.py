"""Optional demo seed data."""

from __future__ import annotations

from datetime import date

import duckdb

from database.connection import get_connection
from utils.config import INITIAL_ELO


DEMO_PLAYERS = [
    "Alex Chen",
    "Jordan Lee",
    "Sam Rivera",
    "Taylor Brooks",
    "Casey Nguyen",
    "Morgan Patel",
    "Riley Quinn",
    "Jamie Ortiz",
    "Avery Kim",
    "Drew Santos",
    "Cameron Blake",
    "Parker Ellis",
]


def seed_demo_players(conn: duckdb.DuckDBPyConnection | None = None) -> int:
    """Insert demo players if the roster is empty. Returns count inserted."""
    conn = conn or get_connection()
    existing = conn.execute("SELECT COUNT(*) FROM players").fetchone()[0]
    if existing:
        return 0

    for name in DEMO_PLAYERS:
        conn.execute(
            """
            INSERT INTO players (name, display_name, active, current_elo)
            VALUES (?, ?, TRUE, ?)
            """,
            [name, name, INITIAL_ELO],
        )
    return len(DEMO_PLAYERS)


def seed_demo_event(conn: duckdb.DuckDBPyConnection | None = None) -> int | None:
    """Create a draft demo event with all active players if none exist."""
    conn = conn or get_connection()
    existing = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    if existing:
        return None

    seed_demo_players(conn)
    conn.execute(
        """
        INSERT INTO events (name, event_date, status, game_to, win_by, num_courts)
        VALUES (?, ?, 'draft', 11, 2, 2)
        """,
        ["Demo Night", date.today()],
    )
    event_id = conn.execute("SELECT id FROM events ORDER BY id DESC LIMIT 1").fetchone()[0]
    player_ids = conn.execute("SELECT id FROM players WHERE active").fetchall()
    for (player_id,) in player_ids:
        conn.execute(
            "INSERT INTO event_players (event_id, player_id) VALUES (?, ?)",
            [event_id, player_id],
        )
    return int(event_id)
