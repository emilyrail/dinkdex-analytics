"""Player persistence."""

from __future__ import annotations

from datetime import datetime

import duckdb
import pandas as pd

from database.connection import get_connection
from models.player import Player
from utils.config import INITIAL_ELO


def _row_to_player(row: tuple) -> Player:
    return Player(
        id=int(row[0]),
        name=row[1],
        display_name=row[2],
        active=bool(row[3]),
        current_elo=float(row[4]),
        created_at=row[5] if isinstance(row[5], datetime) else None,
    )


class PlayerRepository:
    def __init__(self, conn: duckdb.DuckDBPyConnection | None = None) -> None:
        self.conn = conn or get_connection()

    def list_players(self, *, active_only: bool = False) -> list[Player]:
        sql = """
            SELECT id, name, display_name, active, current_elo, created_at
            FROM players p
            WHERE NOT EXISTS (
                SELECT 1 FROM app_meta m
                WHERE m.key = ('hidden_player_' || CAST(p.id AS VARCHAR))
                  AND m.value = '1'
            )
        """
        if active_only:
            sql += " AND active = TRUE"
        sql += " ORDER BY lower(name)"
        return [_row_to_player(r) for r in self.conn.execute(sql).fetchall()]

    def list_players_df(self, *, active_only: bool = False) -> pd.DataFrame:
        sql = """
            SELECT id, name, display_name, active, current_elo, created_at
            FROM players p
            WHERE NOT EXISTS (
                SELECT 1 FROM app_meta m
                WHERE m.key = ('hidden_player_' || CAST(p.id AS VARCHAR))
                  AND m.value = '1'
            )
        """
        if active_only:
            sql += " AND active = TRUE"
        sql += " ORDER BY lower(name)"
        return self.conn.execute(sql).df()

    def get(self, player_id: int) -> Player | None:
        row = self.conn.execute(
            """
            SELECT id, name, display_name, active, current_elo, created_at
            FROM players WHERE id = ?
            """,
            [player_id],
        ).fetchone()
        return _row_to_player(row) if row else None

    def games_played_counts(self) -> dict[int, int]:
        """Completed games per player (from match participation)."""
        rows = self.conn.execute(
            """
            SELECT player_id, COUNT(*) AS games
            FROM (
                SELECT ta.player1_id AS player_id
                FROM matches m
                JOIN scores s ON s.match_id = m.id
                JOIN teams ta ON ta.id = m.team_a_id
                WHERE m.status = 'completed'
                UNION ALL
                SELECT ta.player2_id
                FROM matches m
                JOIN scores s ON s.match_id = m.id
                JOIN teams ta ON ta.id = m.team_a_id
                WHERE m.status = 'completed'
                UNION ALL
                SELECT tb.player1_id
                FROM matches m
                JOIN scores s ON s.match_id = m.id
                JOIN teams tb ON tb.id = m.team_b_id
                WHERE m.status = 'completed'
                UNION ALL
                SELECT tb.player2_id
                FROM matches m
                JOIN scores s ON s.match_id = m.id
                JOIN teams tb ON tb.id = m.team_b_id
                WHERE m.status = 'completed'
            ) AS gp
            GROUP BY player_id
            """
        ).fetchall()
        return {int(pid): int(games) for pid, games in rows}

    def find_by_name(self, name: str) -> Player | None:
        row = self.conn.execute(
            """
            SELECT id, name, display_name, active, current_elo, created_at
            FROM players WHERE lower(name) = lower(?)
            """,
            [name.strip()],
        ).fetchone()
        return _row_to_player(row) if row else None

    def create(
        self,
        name: str,
        *,
        display_name: str | None = None,
        active: bool = True,
        current_elo: float = INITIAL_ELO,
    ) -> Player:
        cleaned = name.strip()
        if not cleaned:
            raise ValueError("Player name is required")
        self.conn.execute(
            """
            INSERT INTO players (name, display_name, active, current_elo)
            VALUES (?, ?, ?, ?)
            """,
            [cleaned, display_name or cleaned, active, current_elo],
        )
        player_id = self.conn.execute("SELECT currval('players_id_seq')").fetchone()[0]
        player = self.get(int(player_id))
        assert player is not None
        return player

    def update(
        self,
        player_id: int,
        *,
        name: str | None = None,
        display_name: str | None = None,
        active: bool | None = None,
    ) -> Player:
        player = self.get(player_id)
        if player is None:
            raise ValueError(f"Player {player_id} not found")

        new_name = name.strip() if name is not None else player.name
        new_display = (
            display_name
            if display_name is not None
            else player.display_name
        )
        new_active = active if active is not None else player.active

        # Fast path: when identity fields are unchanged, update in place.
        # This avoids unnecessary re-keying and name uniqueness collisions.
        identity_changed = (
            new_name != player.name
            or (new_display or "") != (player.display_name or "")
        )
        if not identity_changed:
            self.conn.execute(
                """
                UPDATE players
                SET active = ?
                WHERE id = ?
                """,
                [new_active, player_id],
            )
            updated = self.get(player_id)
            assert updated is not None
            return updated

        # DuckDB currently has FK limitations when updating a referenced parent row.
        # To keep edits working, re-key the player and remap all references atomically.
        return self._rekey_player(
            old_player_id=player_id,
            name=new_name,
            display_name=new_display,
            active=new_active,
            current_elo=player.current_elo,
        )

    def _rekey_player(
        self,
        *,
        old_player_id: int,
        name: str,
        display_name: str | None,
        active: bool,
        current_elo: float,
    ) -> Player:
        self.conn.execute("BEGIN TRANSACTION")
        try:
            # Create replacement player row first.
            self.conn.execute(
                """
                INSERT INTO players (name, display_name, active, current_elo)
                VALUES (?, ?, ?, ?)
                """,
                [name, display_name or name, active, current_elo],
            )
            new_player_id = int(
                self.conn.execute("SELECT currval('players_id_seq')").fetchone()[0]
            )

            # Move direct references.
            self.conn.execute(
                "UPDATE event_players SET player_id = ? WHERE player_id = ?",
                [new_player_id, old_player_id],
            )
            self.conn.execute(
                "UPDATE event_standings SET player_id = ? WHERE player_id = ?",
                [new_player_id, old_player_id],
            )
            self.conn.execute(
                "UPDATE elo_history SET player_id = ? WHERE player_id = ?",
                [new_player_id, old_player_id],
            )

            # Re-map teams that include this player.
            team_rows = self.conn.execute(
                """
                SELECT id, player1_id, player2_id
                FROM teams
                WHERE player1_id = ? OR player2_id = ?
                """,
                [old_player_id, old_player_id],
            ).fetchall()

            for team_id, p1, p2 in team_rows:
                rp1 = new_player_id if int(p1) == old_player_id else int(p1)
                rp2 = new_player_id if int(p2) == old_player_id else int(p2)
                np1, np2 = sorted((rp1, rp2))
                if np1 == np2:
                    continue
                row = self.conn.execute(
                    "SELECT id FROM teams WHERE player1_id = ? AND player2_id = ?",
                    [np1, np2],
                ).fetchone()
                if row:
                    replacement_team_id = int(row[0])
                else:
                    self.conn.execute(
                        "INSERT INTO teams (player1_id, player2_id) VALUES (?, ?)",
                        [np1, np2],
                    )
                    replacement_team_id = int(
                        self.conn.execute("SELECT currval('teams_id_seq')").fetchone()[0]
                    )

                self.conn.execute(
                    "UPDATE matches SET team_a_id = ? WHERE team_a_id = ?",
                    [replacement_team_id, int(team_id)],
                )
                self.conn.execute(
                    "UPDATE matches SET team_b_id = ? WHERE team_b_id = ?",
                    [replacement_team_id, int(team_id)],
                )
                self.conn.execute(
                    "UPDATE scores SET winner_team_id = ? WHERE winner_team_id = ?",
                    [replacement_team_id, int(team_id)],
                )

            # Remove old player if fully detached; otherwise hide from UI lists.
            refs = self.conn.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM teams WHERE player1_id = ? OR player2_id = ?) +
                    (SELECT COUNT(*) FROM event_players WHERE player_id = ?) +
                    (SELECT COUNT(*) FROM event_standings WHERE player_id = ?)
                """,
                [old_player_id, old_player_id, old_player_id, old_player_id],
            ).fetchone()[0]
            if int(refs) == 0:
                self.conn.execute("DELETE FROM players WHERE id = ?", [old_player_id])
            else:
                self.conn.execute(
                    """
                    INSERT INTO app_meta (key, value)
                    VALUES (?, '1')
                    ON CONFLICT (key) DO UPDATE SET value = '1'
                    """,
                    [f"hidden_player_{old_player_id}"],
                )
            self.conn.execute("COMMIT")
        except Exception:
            self.conn.execute("ROLLBACK")
            raise

        updated = self.get(new_player_id)
        assert updated is not None
        return updated
