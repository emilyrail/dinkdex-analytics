"""Rebuild derived Elo history and event standings from fact tables."""

from __future__ import annotations

import duckdb
import pandas as pd

from analytics.elo import apply_delta, default_elo, elo_deltas, k_for_games
from analytics.standings import compute_event_standings
from database.connection import get_connection
from utils.config import ELO_K, INITIAL_ELO


class RecomputeService:
    def __init__(self, conn: duckdb.DuckDBPyConnection | None = None) -> None:
        self.conn = conn or get_connection()

    def rebuild_all(self, *, k: float = ELO_K) -> None:
        """Full chronological Elo replay + refresh all event_standings.

        Runs inside a transaction so a mid-rebuild failure cannot leave every
        player stuck at INITIAL_ELO with an empty elo_history.
        """
        try:
            self.conn.execute("BEGIN TRANSACTION")
            self._rebuild_all_inner(k=k)
            self.conn.commit()
        except Exception:
            try:
                self.conn.execute("ROLLBACK")
            except Exception:
                pass
            from database.connection import reset_connection

            self.conn = reset_connection()
            raise

    def _rebuild_all_inner(self, *, k: float = ELO_K) -> None:
        self.conn.execute("DELETE FROM elo_history")
        self.conn.execute(
            "UPDATE players SET current_elo = ?",
            [INITIAL_ELO],
        )

        matches = self.conn.execute(
            """
            SELECT
                m.id AS match_id,
                m.event_id,
                m.match_order,
                m.team_a_id,
                m.team_b_id,
                s.team_a_score,
                s.team_b_score,
                s.winner_team_id,
                s.submitted_at,
                ta.player1_id AS a1,
                ta.player2_id AS a2,
                tb.player1_id AS b1,
                tb.player2_id AS b2
            FROM matches m
            JOIN scores s ON s.match_id = m.id
            JOIN teams ta ON ta.id = m.team_a_id
            JOIN teams tb ON tb.id = m.team_b_id
            WHERE m.status = 'completed'
            ORDER BY s.submitted_at, m.event_id, m.match_order, m.id
            """
        ).fetchall()

        elos: dict[int, float] = {}
        games_played: dict[int, int] = {}

        def elo_of(pid: int) -> float:
            return elos.get(pid, default_elo())

        for row in matches:
            (
                match_id,
                event_id,
                _order,
                team_a_id,
                team_b_id,
                _sa,
                _sb,
                winner_team_id,
                _submitted,
                a1,
                a2,
                b1,
                b2,
            ) = row

            if int(winner_team_id) == int(team_a_id):
                winners, losers = (int(a1), int(a2)), (int(b1), int(b2))
            else:
                winners, losers = (int(b1), int(b2)), (int(a1), int(a2))

            w_before = (elo_of(winners[0]), elo_of(winners[1]))
            l_before = (elo_of(losers[0]), elo_of(losers[1]))
            winner_ks = (
                k_for_games(games_played.get(winners[0], 0), base_k=k),
                k_for_games(games_played.get(winners[1], 0), base_k=k),
            )
            loser_ks = (
                k_for_games(games_played.get(losers[0], 0), base_k=k),
                k_for_games(games_played.get(losers[1], 0), base_k=k),
            )
            w_deltas, l_deltas = elo_deltas(
                w_before,
                l_before,
                k=k,
                winner_ks=winner_ks,
                loser_ks=loser_ks,
            )

            for pid, before, delta in [
                (winners[0], w_before[0], w_deltas[0]),
                (winners[1], w_before[1], w_deltas[1]),
                (losers[0], l_before[0], l_deltas[0]),
                (losers[1], l_before[1], l_deltas[1]),
            ]:
                after = apply_delta(before, delta)
                elos[pid] = after
                games_played[pid] = games_played.get(pid, 0) + 1
                self.conn.execute(
                    """
                    INSERT INTO elo_history (
                        player_id, match_id, event_id, elo_before, elo_after, delta
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    [pid, match_id, event_id, before, after, delta],
                )

        for pid, elo in elos.items():
            self.conn.execute(
                "UPDATE players SET current_elo = ? WHERE id = ?",
                [elo, pid],
            )

        event_ids = [
            int(r[0])
            for r in self.conn.execute("SELECT id FROM events").fetchall()
        ]
        for event_id in event_ids:
            self.rebuild_event_standings(event_id)

    def rebuild_event_standings(self, event_id: int) -> None:
        self.conn.execute(
            "DELETE FROM event_standings WHERE event_id = ?",
            [event_id],
        )
        player_matches = self.conn.execute(
            """
            SELECT * FROM (
                SELECT
                    m.match_order,
                    ta.player1_id AS player_id,
                    (s.winner_team_id = m.team_a_id) AS won,
                    s.team_a_score AS points_for,
                    s.team_b_score AS points_against
                FROM matches m
                JOIN scores s ON s.match_id = m.id
                JOIN teams ta ON ta.id = m.team_a_id
                WHERE m.event_id = ? AND m.status = 'completed'
                UNION ALL
                SELECT
                    m.match_order,
                    ta.player2_id,
                    (s.winner_team_id = m.team_a_id),
                    s.team_a_score,
                    s.team_b_score
                FROM matches m
                JOIN scores s ON s.match_id = m.id
                JOIN teams ta ON ta.id = m.team_a_id
                WHERE m.event_id = ? AND m.status = 'completed'
                UNION ALL
                SELECT
                    m.match_order,
                    tb.player1_id,
                    (s.winner_team_id = m.team_b_id),
                    s.team_b_score,
                    s.team_a_score
                FROM matches m
                JOIN scores s ON s.match_id = m.id
                JOIN teams tb ON tb.id = m.team_b_id
                WHERE m.event_id = ? AND m.status = 'completed'
                UNION ALL
                SELECT
                    m.match_order,
                    tb.player2_id,
                    (s.winner_team_id = m.team_b_id),
                    s.team_b_score,
                    s.team_a_score
                FROM matches m
                JOIN scores s ON s.match_id = m.id
                JOIN teams tb ON tb.id = m.team_b_id
                WHERE m.event_id = ? AND m.status = 'completed'
            ) AS player_match_rows
            """,
            [event_id, event_id, event_id, event_id],
        ).df()

        standings = compute_event_standings(player_matches)

        # Attach current player elo (post-rebuild)
        elo_map = {
            int(r[0]): float(r[1])
            for r in self.conn.execute("SELECT id, current_elo FROM players").fetchall()
        }

        # Include attendees with 0 games
        attendee_ids = [
            int(r[0])
            for r in self.conn.execute(
                "SELECT player_id FROM event_players WHERE event_id = ?",
                [event_id],
            ).fetchall()
        ]
        present = set(standings["player_id"].astype(int)) if not standings.empty else set()
        extra_rows = []
        for pid in attendee_ids:
            if pid not in present:
                extra_rows.append(
                    {
                        "player_id": pid,
                        "wins": 0,
                        "losses": 0,
                        "points_for": 0,
                        "points_against": 0,
                        "point_diff": 0,
                        "win_pct": 0.0,
                        "current_streak": 0,
                    }
                )
        if extra_rows:
            standings = pd.concat([standings, pd.DataFrame(extra_rows)], ignore_index=True)

        for _, row in standings.iterrows():
            pid = int(row["player_id"])
            self.conn.execute(
                """
                INSERT INTO event_standings (
                    event_id, player_id, wins, losses, points_for, points_against,
                    point_diff, win_pct, elo, current_streak
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    event_id,
                    pid,
                    int(row["wins"]),
                    int(row["losses"]),
                    int(row["points_for"]),
                    int(row["points_against"]),
                    float(row["point_diff"]),
                    float(row["win_pct"]),
                    elo_map.get(pid, INITIAL_ELO),
                    int(row["current_streak"]),
                ],
            )

    def standings_df(self, event_id: int) -> pd.DataFrame:
        return self.conn.execute(
            """
            SELECT
                es.player_id,
                p.name,
                p.display_name,
                es.wins,
                es.losses,
                es.points_for,
                es.points_against,
                es.point_diff,
                es.win_pct,
                es.elo,
                es.current_streak
            FROM event_standings es
            JOIN players p ON p.id = es.player_id
            WHERE es.event_id = ?
            ORDER BY es.wins DESC, es.point_diff DESC, es.elo DESC, lower(p.name)
            """,
            [event_id],
        ).df()
