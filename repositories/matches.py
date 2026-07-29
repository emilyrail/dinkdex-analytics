"""Team and match persistence."""

from __future__ import annotations

from datetime import datetime

import duckdb
import pandas as pd

from database.connection import get_connection
from models.enums import MatchStatus
from models.match import Match

_MATCH_SELECT = """
    SELECT id, event_id, round_number, match_order, court,
           team_a_id, team_b_id, status, import_batch_id, scheduled_at,
           COALESCE(is_finale, FALSE) AS is_finale, finale_label
    FROM matches
"""


def normalize_pair(player_a: int, player_b: int) -> tuple[int, int]:
    if player_a == player_b:
        raise ValueError("Partners must be different players")
    return (min(player_a, player_b), max(player_a, player_b))


def _row_to_match(row: tuple) -> Match:
    return Match(
        id=int(row[0]),
        event_id=int(row[1]),
        round_number=int(row[2]),
        match_order=int(row[3]),
        court=int(row[4]) if row[4] is not None else None,
        team_a_id=int(row[5]),
        team_b_id=int(row[6]),
        status=MatchStatus(row[7]),
        import_batch_id=int(row[8]) if row[8] is not None else None,
        scheduled_at=row[9] if isinstance(row[9], datetime) else None,
        is_finale=bool(row[10]) if len(row) > 10 and row[10] is not None else False,
        finale_label=str(row[11]) if len(row) > 11 and row[11] is not None else None,
    )


class TeamRepository:
    def __init__(self, conn: duckdb.DuckDBPyConnection | None = None) -> None:
        self.conn = conn or get_connection()

    def get_or_create(self, player_a: int, player_b: int) -> int:
        p1, p2 = normalize_pair(player_a, player_b)
        row = self.conn.execute(
            "SELECT id FROM teams WHERE player1_id = ? AND player2_id = ?",
            [p1, p2],
        ).fetchone()
        if row:
            return int(row[0])
        self.conn.execute(
            "INSERT INTO teams (player1_id, player2_id) VALUES (?, ?)",
            [p1, p2],
        )
        return int(self.conn.execute("SELECT currval('teams_id_seq')").fetchone()[0])

    def get_player_ids(self, team_id: int) -> tuple[int, int]:
        row = self.conn.execute(
            "SELECT player1_id, player2_id FROM teams WHERE id = ?",
            [team_id],
        ).fetchone()
        if not row:
            raise ValueError(f"Team {team_id} not found")
        return int(row[0]), int(row[1])


class MatchRepository:
    def __init__(self, conn: duckdb.DuckDBPyConnection | None = None) -> None:
        self.conn = conn or get_connection()
        self.teams = TeamRepository(self.conn)

    def list_for_event(self, event_id: int) -> list[Match]:
        rows = self.conn.execute(
            f"""
            {_MATCH_SELECT}
            WHERE event_id = ?
            ORDER BY match_order, id
            """,
            [event_id],
        ).fetchall()
        return [_row_to_match(r) for r in rows]

    def get(self, match_id: int) -> Match | None:
        row = self.conn.execute(
            f"""
            {_MATCH_SELECT}
            WHERE id = ?
            """,
            [match_id],
        ).fetchone()
        return _row_to_match(row) if row else None

    def next_scheduled(self, event_id: int) -> Match | None:
        row = self.conn.execute(
            f"""
            {_MATCH_SELECT}
            WHERE event_id = ? AND status = 'scheduled'
            ORDER BY match_order, id
            LIMIT 1
            """,
            [event_id],
        ).fetchone()
        return _row_to_match(row) if row else None

    def create(
        self,
        event_id: int,
        *,
        team_a_players: tuple[int, int],
        team_b_players: tuple[int, int],
        round_number: int = 1,
        match_order: int | None = None,
        court: int | None = None,
        status: MatchStatus = MatchStatus.SCHEDULED,
        is_finale: bool = False,
        finale_label: str | None = None,
    ) -> Match:
        all_players = set(team_a_players) | set(team_b_players)
        if len(all_players) != 4:
            raise ValueError("A match needs four distinct players")

        team_a_id = self.teams.get_or_create(*team_a_players)
        team_b_id = self.teams.get_or_create(*team_b_players)
        if team_a_id == team_b_id:
            raise ValueError("Teams must be different")

        if match_order is None:
            row = self.conn.execute(
                "SELECT COALESCE(MAX(match_order), 0) + 1 FROM matches WHERE event_id = ?",
                [event_id],
            ).fetchone()
            match_order = int(row[0])

        label = finale_label if is_finale else None
        self.conn.execute(
            """
            INSERT INTO matches (
                event_id, round_number, match_order, court,
                team_a_id, team_b_id, status, is_finale, finale_label
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                event_id,
                round_number,
                match_order,
                court,
                team_a_id,
                team_b_id,
                status.value,
                bool(is_finale),
                label,
            ],
        )
        match_id = int(self.conn.execute("SELECT currval('matches_id_seq')").fetchone()[0])
        match = self.get(match_id)
        assert match is not None
        return match

    def update_lineup(
        self,
        match_id: int,
        *,
        team_a_players: tuple[int, int] | None = None,
        team_b_players: tuple[int, int] | None = None,
        round_number: int | None = None,
        match_order: int | None = None,
        court: int | None = None,
        status: MatchStatus | None = None,
        is_finale: bool | None = None,
        finale_label: str | None = None,
    ) -> Match:
        match = self.get(match_id)
        if match is None:
            raise ValueError(f"Match {match_id} not found")

        team_a_id = match.team_a_id
        team_b_id = match.team_b_id
        if team_a_players is not None:
            team_a_id = self.teams.get_or_create(*team_a_players)
        if team_b_players is not None:
            team_b_id = self.teams.get_or_create(*team_b_players)

        if team_a_players is not None and team_b_players is not None:
            all_players = set(team_a_players) | set(team_b_players)
            if len(all_players) != 4:
                raise ValueError("A match needs four distinct players")

        next_is_finale = match.is_finale if is_finale is None else bool(is_finale)
        if finale_label is not None:
            next_label = finale_label if next_is_finale else None
        else:
            next_label = match.finale_label if next_is_finale else None

        self.conn.execute(
            """
            UPDATE matches
            SET team_a_id = ?,
                team_b_id = ?,
                round_number = ?,
                match_order = ?,
                court = ?,
                status = ?,
                is_finale = ?,
                finale_label = ?
            WHERE id = ?
            """,
            [
                team_a_id,
                team_b_id,
                round_number if round_number is not None else match.round_number,
                match_order if match_order is not None else match.match_order,
                court if court is not None else match.court,
                (status or match.status).value,
                next_is_finale,
                next_label,
                match_id,
            ],
        )
        updated = self.get(match_id)
        assert updated is not None
        return updated

    def delete(self, match_id: int) -> None:
        # Only allow deleting matches without scores (caller should enforce)
        self.conn.execute("DELETE FROM matches WHERE id = ?", [match_id])

    def set_status(self, match_id: int, status: MatchStatus) -> None:
        self.conn.execute(
            "UPDATE matches SET status = ? WHERE id = ?",
            [status.value, match_id],
        )

    def event_schedule_df(self, event_id: int) -> pd.DataFrame:
        return self.conn.execute(
            """
            SELECT
                m.id AS match_id,
                m.round_number,
                m.match_order,
                m.court,
                m.status,
                COALESCE(m.is_finale, FALSE) AS is_finale,
                m.finale_label,
                CASE
                    WHEN COALESCE(m.is_finale, FALSE) AND m.finale_label IS NOT NULL
                        THEN 'Finale - ' || m.finale_label
                    WHEN COALESCE(m.is_finale, FALSE) THEN 'Finale'
                    ELSE NULL
                END AS finale_display,
                m.team_a_id,
                m.team_b_id,
                ta.player1_id AS a1_id,
                ta.player2_id AS a2_id,
                tb.player1_id AS b1_id,
                tb.player2_id AS b2_id,
                pa1.name AS a1,
                pa2.name AS a2,
                pb1.name AS b1,
                pb2.name AS b2,
                s.team_a_score,
                s.team_b_score
            FROM matches m
            JOIN teams ta ON ta.id = m.team_a_id
            JOIN teams tb ON tb.id = m.team_b_id
            JOIN players pa1 ON pa1.id = ta.player1_id
            JOIN players pa2 ON pa2.id = ta.player2_id
            JOIN players pb1 ON pb1.id = tb.player1_id
            JOIN players pb2 ON pb2.id = tb.player2_id
            LEFT JOIN scores s ON s.match_id = m.id
            WHERE m.event_id = ?
            ORDER BY m.match_order, m.id
            """,
            [event_id],
        ).df()
