"""Score persistence."""

from __future__ import annotations

from datetime import datetime

import duckdb

from database.connection import get_connection
from models.score import Score


def _row_to_score(row: tuple) -> Score:
    return Score(
        id=int(row[0]),
        match_id=int(row[1]),
        team_a_score=int(row[2]),
        team_b_score=int(row[3]),
        winner_team_id=int(row[4]),
        submitted_at=row[5] if isinstance(row[5], datetime) else None,
        updated_at=row[6] if isinstance(row[6], datetime) else None,
    )


class ScoreRepository:
    def __init__(self, conn: duckdb.DuckDBPyConnection | None = None) -> None:
        self.conn = conn or get_connection()

    def get_for_match(self, match_id: int) -> Score | None:
        row = self.conn.execute(
            """
            SELECT id, match_id, team_a_score, team_b_score,
                   winner_team_id, submitted_at, updated_at
            FROM scores WHERE match_id = ?
            """,
            [match_id],
        ).fetchone()
        return _row_to_score(row) if row else None

    def insert(
        self,
        match_id: int,
        team_a_score: int,
        team_b_score: int,
        winner_team_id: int,
    ) -> Score:
        self.conn.execute(
            """
            INSERT INTO scores (
                match_id, team_a_score, team_b_score, winner_team_id
            ) VALUES (?, ?, ?, ?)
            """,
            [match_id, team_a_score, team_b_score, winner_team_id],
        )
        score = self.get_for_match(match_id)
        assert score is not None
        return score

    def update(
        self,
        match_id: int,
        team_a_score: int,
        team_b_score: int,
        winner_team_id: int,
    ) -> Score:
        self.conn.execute(
            """
            UPDATE scores
            SET team_a_score = ?,
                team_b_score = ?,
                winner_team_id = ?,
                updated_at = current_timestamp
            WHERE match_id = ?
            """,
            [team_a_score, team_b_score, winner_team_id, match_id],
        )
        score = self.get_for_match(match_id)
        assert score is not None
        return score

    def delete_for_match(self, match_id: int) -> None:
        self.conn.execute("DELETE FROM scores WHERE match_id = ?", [match_id])
