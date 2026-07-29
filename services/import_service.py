"""Historical CSV import service."""

from __future__ import annotations

import duckdb
import pandas as pd

from database.connection import get_connection
from import_.parsers import normalize_matches_df
from import_.validators import validate_matches_df
from services.recompute_service import RecomputeService


class ImportService:
    def __init__(self, conn: duckdb.DuckDBPyConnection | None = None) -> None:
        self.conn = conn or get_connection()

    def validate(self, df: pd.DataFrame) -> list[str]:
        return validate_matches_df(df)

    def import_matches(
        self,
        df: pd.DataFrame,
        *,
        source_filename: str,
        mark_events_completed: bool = True,
    ) -> dict:
        errors = self.validate(df)
        if errors:
            raise ValueError("; ".join(errors))

        normalized = normalize_matches_df(df)
        row_count = len(normalized)
        self.conn.execute("BEGIN TRANSACTION")
        try:
            self.conn.execute(
                """
                INSERT INTO import_batches (source_filename, status, row_count, notes)
                VALUES (?, 'committed', ?, ?)
                """,
                [source_filename, row_count, "CSV import"],
            )
            batch_id = self.conn.execute(
                "SELECT id FROM import_batches ORDER BY id DESC LIMIT 1"
            ).fetchone()[0]

            player_ids: dict[str, int] = {
                name: int(pid)
                for pid, name in self.conn.execute("SELECT id, name FROM players").fetchall()
            }

            def ensure_player(name: str) -> int:
                if name in player_ids:
                    return player_ids[name]
                self.conn.execute(
                    "INSERT INTO players (name, display_name, active, current_elo) VALUES (?, ?, TRUE, 1000.0)",
                    [name, name],
                )
                pid = int(
                    self.conn.execute(
                        "SELECT id FROM players WHERE name = ?",
                        [name],
                    ).fetchone()[0]
                )
                player_ids[name] = pid
                return pid

            def ensure_team(a: int, b: int) -> int:
                p1, p2 = sorted((a, b))
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
                return int(
                    self.conn.execute(
                        "SELECT id FROM teams WHERE player1_id = ? AND player2_id = ?",
                        [p1, p2],
                    ).fetchone()[0]
                )

            event_map: dict[tuple, int] = {}
            inserted_matches = 0
            for _, row in normalized.iterrows():
                event_name = row.get("event_name") or f"Pickleball {row['event_date']}"
                event_key = (str(row["event_date"]), str(event_name))
                if event_key not in event_map:
                    existing = self.conn.execute(
                        "SELECT id FROM events WHERE event_date = ? AND name = ?",
                        [row["event_date"], event_name],
                    ).fetchone()
                    if existing:
                        event_id = int(existing[0])
                    else:
                        self.conn.execute(
                            """
                            INSERT INTO events (name, event_date, status, game_to, win_by, num_courts)
                            VALUES (?, ?, ?, 11, 2, 2)
                            """,
                            [event_name, row["event_date"], "completed" if mark_events_completed else "draft"],
                        )
                        event_id = int(
                            self.conn.execute(
                                "SELECT id FROM events WHERE event_date = ? AND name = ?",
                                [row["event_date"], event_name],
                            ).fetchone()[0]
                        )
                    event_map[event_key] = event_id

                event_id = event_map[event_key]
                pids = [
                    ensure_player(str(row["player_a1"])),
                    ensure_player(str(row["player_a2"])),
                    ensure_player(str(row["player_b1"])),
                    ensure_player(str(row["player_b2"])),
                ]
                for pid in pids:
                    self.conn.execute(
                        """
                        INSERT INTO event_players (event_id, player_id)
                        SELECT ?, ?
                        WHERE NOT EXISTS (
                            SELECT 1 FROM event_players WHERE event_id = ? AND player_id = ?
                        )
                        """,
                        [event_id, pid, event_id, pid],
                    )

                ta = ensure_team(pids[0], pids[1])
                tb = ensure_team(pids[2], pids[3])

                self.conn.execute(
                    """
                    INSERT INTO matches (
                        event_id, round_number, match_order, court,
                        team_a_id, team_b_id, status, import_batch_id,
                        is_finale, finale_label
                    )
                    VALUES (?, ?, ?, ?, ?, ?, 'completed', ?, ?, ?)
                    """,
                    [
                        event_id,
                        int(row["round_number"]),
                        int(row["match_order"]),
                        row["court"],
                        ta,
                        tb,
                        batch_id,
                        bool(row.get("is_finale", False)),
                        row.get("finale_label"),
                    ],
                )
                match_id = int(self.conn.execute("SELECT id FROM matches ORDER BY id DESC LIMIT 1").fetchone()[0])
                sa = int(row["score_a"])
                sb = int(row["score_b"])
                winner = ta if sa > sb else tb
                self.conn.execute(
                    """
                    INSERT INTO scores (match_id, team_a_score, team_b_score, winner_team_id)
                    VALUES (?, ?, ?, ?)
                    """,
                    [match_id, sa, sb, winner],
                )
                inserted_matches += 1

            self.conn.commit()
        except Exception:
            self.conn.execute("ROLLBACK")
            raise

        RecomputeService(self.conn).rebuild_all()
        return {
            "batch_id": int(batch_id),
            "rows_imported": inserted_matches,
            "events_touched": len(event_map),
            "players_total": int(self.conn.execute("SELECT COUNT(*) FROM players").fetchone()[0]),
        }
