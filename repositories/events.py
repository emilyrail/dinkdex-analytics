"""Event persistence."""

from __future__ import annotations

from datetime import date, datetime

import duckdb
import pandas as pd

from database.connection import get_connection
from models.enums import EventStatus
from models.event import Event
from utils.config import DEFAULT_GAME_TO, DEFAULT_NUM_COURTS, DEFAULT_WIN_BY


def _row_to_event(row: tuple) -> Event:
    if row is None or len(row) < 7:
        raise ValueError(f"Invalid events row (expected >=7 cols, got {row!r})")
    return Event(
        id=int(row[0]),
        name=row[1],
        event_date=row[2] if isinstance(row[2], date) else date.fromisoformat(str(row[2])),
        status=EventStatus(row[3]),
        game_to=int(row[4]),
        win_by=int(row[5]),
        num_courts=int(row[6]),
        created_at=row[7] if len(row) > 7 and isinstance(row[7], datetime) else None,
    )


class EventRepository:
    def __init__(self, conn: duckdb.DuckDBPyConnection | None = None) -> None:
        self.conn = conn or get_connection()

    def list_events(self) -> list[Event]:
        rows = self.conn.execute(
            """
            SELECT id, name, event_date, status, game_to, win_by, num_courts, created_at
            FROM events
            ORDER BY event_date DESC, id DESC
            """
        ).fetchall()
        return [_row_to_event(r) for r in rows]

    def list_events_df(self) -> pd.DataFrame:
        return self.conn.execute(
            """
            SELECT id, name, event_date, status, game_to, win_by, num_courts, created_at
            FROM events
            ORDER BY event_date DESC, id DESC
            """
        ).df()

    def get(self, event_id: int) -> Event | None:
        sql = """
            SELECT id, name, event_date, status, game_to, win_by, num_courts, created_at
            FROM events WHERE id = ?
            """
        try:
            row = self.conn.execute(sql, [event_id]).fetchone()
        except duckdb.Error:
            from database.connection import reset_connection

            self.conn = reset_connection()
            row = self.conn.execute(sql, [event_id]).fetchone()
        if not row:
            return None
        try:
            return _row_to_event(row)
        except (ValueError, IndexError, TypeError):
            from database.connection import reset_connection

            self.conn = reset_connection()
            row = self.conn.execute(sql, [event_id]).fetchone()
            return _row_to_event(row) if row else None

    def create(
        self,
        name: str,
        event_date: date,
        *,
        status: EventStatus = EventStatus.DRAFT,
        game_to: int = DEFAULT_GAME_TO,
        win_by: int = DEFAULT_WIN_BY,
        num_courts: int = DEFAULT_NUM_COURTS,
    ) -> Event:
        cleaned = name.strip()
        if not cleaned:
            raise ValueError("Event name is required")
        self.conn.execute(
            """
            INSERT INTO events (name, event_date, status, game_to, win_by, num_courts)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [cleaned, event_date, status.value, game_to, win_by, num_courts],
        )
        event_id = self.conn.execute("SELECT currval('events_id_seq')").fetchone()[0]
        event = self.get(int(event_id))
        assert event is not None
        return event

    def update(
        self,
        event_id: int,
        *,
        name: str | None = None,
        event_date: date | None = None,
        status: EventStatus | None = None,
        game_to: int | None = None,
        win_by: int | None = None,
        num_courts: int | None = None,
    ) -> Event:
        event = self.get(event_id)
        if event is None:
            raise ValueError(f"Event {event_id} not found")

        self.conn.execute(
            """
            UPDATE events
            SET name = ?,
                event_date = ?,
                status = ?,
                game_to = ?,
                win_by = ?,
                num_courts = ?
            WHERE id = ?
            """,
            [
                name.strip() if name is not None else event.name,
                event_date if event_date is not None else event.event_date,
                (status or event.status).value,
                game_to if game_to is not None else event.game_to,
                win_by if win_by is not None else event.win_by,
                num_courts if num_courts is not None else event.num_courts,
                event_id,
            ],
        )
        updated = self.get(event_id)
        assert updated is not None
        return updated

    def set_players(self, event_id: int, player_ids: list[int]) -> None:
        self.conn.execute("DELETE FROM event_players WHERE event_id = ?", [event_id])
        for player_id in player_ids:
            self.conn.execute(
                "INSERT INTO event_players (event_id, player_id) VALUES (?, ?)",
                [event_id, player_id],
            )

    def get_player_ids(self, event_id: int) -> list[int]:
        rows = self.conn.execute(
            """
            SELECT player_id FROM event_players
            WHERE event_id = ?
            ORDER BY player_id
            """,
            [event_id],
        ).fetchall()
        return [int(r[0]) for r in rows]

    def get_players_df(self, event_id: int) -> pd.DataFrame:
        return self.conn.execute(
            """
            SELECT p.id, p.name, p.display_name, p.active, p.current_elo
            FROM event_players ep
            JOIN players p ON p.id = ep.player_id
            WHERE ep.event_id = ?
            ORDER BY lower(p.name)
            """,
            [event_id],
        ).df()
