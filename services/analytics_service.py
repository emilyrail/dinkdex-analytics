"""Analytics aggregations for event and historical views."""

from __future__ import annotations

import duckdb
import pandas as pd

from database.connection import get_connection


class AnalyticsService:
    def __init__(self, conn: duckdb.DuckDBPyConnection | None = None) -> None:
        self.conn = conn or get_connection()

    def event_standings(self, event_id: int) -> pd.DataFrame:
        return self.conn.execute(
            """
            SELECT
                es.player_id,
                COALESCE(p.display_name, p.name) AS player,
                es.wins,
                es.losses,
                es.win_pct,
                es.points_for,
                es.points_against,
                es.point_diff,
                es.elo,
                es.current_streak
            FROM event_standings es
            JOIN players p ON p.id = es.player_id
            WHERE es.event_id = ?
            ORDER BY es.wins DESC, es.point_diff DESC, es.elo DESC
            """,
            [event_id],
        ).df()

    def event_summary(self, event_id: int) -> dict:
        row = self.conn.execute(
            """
            SELECT
                COUNT(*) AS matches_played,
                SUM(s.team_a_score + s.team_b_score) AS total_points
            FROM matches m
            LEFT JOIN scores s ON s.match_id = m.id
            WHERE m.event_id = ? AND m.status = 'completed'
            """,
            [event_id],
        ).fetchone()
        return {
            "matches_played": int(row[0] or 0),
            "total_points": int(row[1] or 0),
        }

    def court_stats(self, event_id: int) -> pd.DataFrame:
        return self.conn.execute(
            """
            SELECT
                m.court,
                COUNT(*) AS matches,
                AVG(s.team_a_score + s.team_b_score) AS avg_total_points,
                AVG(ABS(s.team_a_score - s.team_b_score)) AS avg_margin
            FROM matches m
            JOIN scores s ON s.match_id = m.id
            WHERE m.event_id = ? AND m.status = 'completed'
            GROUP BY m.court
            ORDER BY m.court
            """,
            [event_id],
        ).df()

    def elo_timeline(self, player_id: int) -> pd.DataFrame:
        return self.conn.execute(
            """
            SELECT
                eh.created_at,
                eh.elo_after AS elo,
                eh.event_id,
                e.event_date,
                e.name AS event_name
            FROM elo_history eh
            JOIN events e ON e.id = eh.event_id
            WHERE eh.player_id = ?
            ORDER BY eh.created_at, eh.id
            """,
            [player_id],
        ).df()

    def player_overview(self, player_id: int, event_id: int | None = None) -> dict:
        event_filter = ""
        params: list[object] = [player_id, player_id, player_id, player_id, player_id, player_id, player_id, player_id, player_id, player_id]
        if event_id is not None:
            event_filter = " AND m.event_id = ?"
            params.append(event_id)
        row = self.conn.execute(
            f"""
            WITH player_games AS (
                SELECT
                    m.id AS match_id,
                    m.event_id,
                    m.match_order,
                    CASE
                        WHEN ta.player1_id = ? OR ta.player2_id = ? THEN s.team_a_score
                        ELSE s.team_b_score
                    END AS points_for,
                    CASE
                        WHEN ta.player1_id = ? OR ta.player2_id = ? THEN s.team_b_score
                        ELSE s.team_a_score
                    END AS points_against,
                    CASE
                        WHEN ta.player1_id = ? OR ta.player2_id = ? THEN (s.winner_team_id = m.team_a_id)
                        ELSE (s.winner_team_id = m.team_b_id)
                    END AS won
                FROM matches m
                JOIN scores s ON s.match_id = m.id
                JOIN teams ta ON ta.id = m.team_a_id
                JOIN teams tb ON tb.id = m.team_b_id
                WHERE m.status = 'completed'
                  AND (
                    ta.player1_id = ? OR ta.player2_id = ?
                    OR tb.player1_id = ? OR tb.player2_id = ?
                  )
                  {event_filter}
            )
            SELECT
                COUNT(*) AS games,
                SUM(CASE WHEN won THEN 1 ELSE 0 END) AS wins,
                SUM(CASE WHEN won THEN 0 ELSE 1 END) AS losses,
                SUM(points_for) AS points_for,
                SUM(points_against) AS points_against
            FROM player_games
            """,
            params,
        ).fetchone()
        games = int(row[0] or 0)
        wins = int(row[1] or 0)
        losses = int(row[2] or 0)
        points_for = int(row[3] or 0)
        points_against = int(row[4] or 0)
        return {
            "games": games,
            "wins": wins,
            "losses": losses,
            "win_pct": (wins / games) if games else 0.0,
            "points_for": points_for,
            "points_against": points_against,
            "point_diff": points_for - points_against,
        }

    def partner_win_rates(self, player_id: int, min_games: int = 1, event_id: int | None = None) -> pd.DataFrame:
        event_filter = ""
        params: list[object] = [
            player_id,
            player_id,
            player_id,
            player_id,
            player_id,
            player_id,
            player_id,
            player_id,
            player_id,
            player_id,
            player_id,
        ]
        if event_id is not None:
            event_filter = " AND m.event_id = ?"
            params.append(event_id)
        params.append(min_games)
        return self.conn.execute(
            f"""
            WITH player_partner_games AS (
                SELECT
                    CASE
                        WHEN ta.player1_id = ? THEN ta.player2_id
                        WHEN ta.player2_id = ? THEN ta.player1_id
                        WHEN tb.player1_id = ? THEN tb.player2_id
                        ELSE tb.player1_id
                    END AS partner_id,
                    CASE
                        WHEN ta.player1_id = ? OR ta.player2_id = ? THEN (s.winner_team_id = m.team_a_id)
                        ELSE (s.winner_team_id = m.team_b_id)
                    END AS won,
                    CASE
                        WHEN ta.player1_id = ? OR ta.player2_id = ? THEN (s.team_a_score - s.team_b_score)
                        ELSE (s.team_b_score - s.team_a_score)
                    END AS margin
                FROM matches m
                JOIN scores s ON s.match_id = m.id
                JOIN teams ta ON ta.id = m.team_a_id
                JOIN teams tb ON tb.id = m.team_b_id
                WHERE m.status = 'completed'
                  AND (
                    ta.player1_id = ? OR ta.player2_id = ?
                    OR tb.player1_id = ? OR tb.player2_id = ?
                  )
                  {event_filter}
            )
            SELECT
                p.id AS partner_id,
                COALESCE(p.display_name, p.name) AS partner,
                COUNT(*) AS games,
                SUM(CASE WHEN won THEN 1 ELSE 0 END) AS wins,
                SUM(CASE WHEN won THEN 0 ELSE 1 END) AS losses,
                AVG(CASE WHEN won THEN 1.0 ELSE 0.0 END) AS win_rate,
                AVG(margin) AS avg_margin
            FROM player_partner_games g
            JOIN players p ON p.id = g.partner_id
            GROUP BY p.id, p.name, p.display_name
            HAVING COUNT(*) >= ?
            ORDER BY win_rate DESC, games DESC, lower(p.name)
            """,
            params,
        ).df()

    def head_to_head(self, player_id: int, event_id: int | None = None) -> pd.DataFrame:
        event_filter = ""
        params: list[object] = [
            player_id,
            player_id,
            player_id,
            player_id,
            player_id,
            player_id,
            player_id,
            player_id,
            player_id,
            player_id,
            player_id,
            player_id,
        ]
        if event_id is not None:
            event_filter = " AND m.event_id = ?"
            params.append(event_id)
        return self.conn.execute(
            f"""
            WITH player_vs AS (
                SELECT
                    opp.id AS opponent_id,
                    COALESCE(opp.display_name, opp.name) AS opponent,
                    CASE
                        WHEN ta.player1_id = ? OR ta.player2_id = ? THEN (s.winner_team_id = m.team_a_id)
                        ELSE (s.winner_team_id = m.team_b_id)
                    END AS won,
                    CASE
                        WHEN ta.player1_id = ? OR ta.player2_id = ? THEN (s.team_a_score - s.team_b_score)
                        ELSE (s.team_b_score - s.team_a_score)
                    END AS margin
                FROM matches m
                JOIN scores s ON s.match_id = m.id
                JOIN teams ta ON ta.id = m.team_a_id
                JOIN teams tb ON tb.id = m.team_b_id
                JOIN players opp ON opp.id IN (
                    CASE WHEN ta.player1_id = ? OR ta.player2_id = ? THEN tb.player1_id ELSE ta.player1_id END,
                    CASE WHEN ta.player1_id = ? OR ta.player2_id = ? THEN tb.player2_id ELSE ta.player2_id END
                )
                WHERE m.status = 'completed'
                  AND (
                    ta.player1_id = ? OR ta.player2_id = ?
                    OR tb.player1_id = ? OR tb.player2_id = ?
                  )
                  {event_filter}
            )
            SELECT
                opponent_id,
                opponent,
                COUNT(*) AS games,
                SUM(CASE WHEN won THEN 1 ELSE 0 END) AS wins,
                SUM(CASE WHEN won THEN 0 ELSE 1 END) AS losses,
                AVG(CASE WHEN won THEN 1.0 ELSE 0.0 END) AS win_rate,
                AVG(margin) AS avg_margin
            FROM player_vs
            GROUP BY opponent_id, opponent
            ORDER BY games DESC, win_rate DESC
            """,
            params,
        ).df()

    def event_best_partners(self, event_id: int) -> pd.DataFrame:
        return self.conn.execute(
            """
            WITH partner_games AS (
                SELECT
                    ta.player1_id AS p1,
                    ta.player2_id AS p2,
                    (s.winner_team_id = m.team_a_id) AS won,
                    (s.team_a_score - s.team_b_score) AS margin
                FROM matches m
                JOIN scores s ON s.match_id = m.id
                JOIN teams ta ON ta.id = m.team_a_id
                WHERE m.event_id = ? AND m.status = 'completed'
                UNION ALL
                SELECT
                    tb.player1_id AS p1,
                    tb.player2_id AS p2,
                    (s.winner_team_id = m.team_b_id) AS won,
                    (s.team_b_score - s.team_a_score) AS margin
                FROM matches m
                JOIN scores s ON s.match_id = m.id
                JOIN teams tb ON tb.id = m.team_b_id
                WHERE m.event_id = ? AND m.status = 'completed'
            )
            SELECT
                pg.p1 AS player1_id,
                pg.p2 AS player2_id,
                COALESCE(p1.display_name, p1.name) || ' / ' || COALESCE(p2.display_name, p2.name) AS partners,
                COUNT(*) AS games,
                SUM(CASE WHEN pg.won THEN 1 ELSE 0 END) AS wins,
                SUM(CASE WHEN pg.won THEN 0 ELSE 1 END) AS losses,
                AVG(CASE WHEN pg.won THEN 1.0 ELSE 0.0 END) AS win_rate,
                AVG(pg.margin) AS avg_margin
            FROM partner_games pg
            JOIN players p1 ON p1.id = pg.p1
            JOIN players p2 ON p2.id = pg.p2
            GROUP BY pg.p1, pg.p2, COALESCE(p1.display_name, p1.name), COALESCE(p2.display_name, p2.name)
            ORDER BY win_rate DESC, games DESC, partners
            """,
            [event_id, event_id],
        ).df()

    def weekly_trends(self) -> pd.DataFrame:
        return self.conn.execute(
            """
            WITH results AS (
                SELECT
                    CAST(e.event_date AS DATE) AS event_date,
                    m.event_id,
                    COUNT(*) AS matches_played
                FROM matches m
                JOIN events e ON e.id = m.event_id
                WHERE m.status = 'completed'
                GROUP BY e.event_date, m.event_id
            )
            SELECT
                event_date,
                COUNT(*) AS events,
                SUM(matches_played) AS total_matches
            FROM results
            GROUP BY event_date
            ORDER BY event_date
            """
        ).df()

    def biggest_upsets(self, limit: int = 10) -> pd.DataFrame:
        return self.conn.execute(
            """
            WITH match_elos AS (
                SELECT
                    m.id AS match_id,
                    CAST(e.event_date AS DATE) AS event_date,
                    m.match_order,
                    ta.player1_id AS a1, ta.player2_id AS a2,
                    tb.player1_id AS b1, tb.player2_id AS b2,
                    m.team_a_id, m.team_b_id,
                    s.team_a_score, s.team_b_score, s.winner_team_id
                FROM matches m
                JOIN scores s ON s.match_id = m.id
                JOIN events e ON e.id = m.event_id
                JOIN teams ta ON ta.id = m.team_a_id
                JOIN teams tb ON tb.id = m.team_b_id
                WHERE m.status = 'completed'
            )
            SELECT
                me.event_date,
                me.match_id,
                me.match_order,
                COALESCE(pa1.display_name, pa1.name) AS a1_name,
                COALESCE(pa2.display_name, pa2.name) AS a2_name,
                COALESCE(pb1.display_name, pb1.name) AS b1_name,
                COALESCE(pb2.display_name, pb2.name) AS b2_name,
                me.team_a_score,
                me.team_b_score,
                ABS(
                    ((pa1.current_elo + pa2.current_elo) / 2.0) -
                    ((pb1.current_elo + pb2.current_elo) / 2.0)
                ) AS elo_gap
            FROM match_elos me
            JOIN players pa1 ON pa1.id = me.a1
            JOIN players pa2 ON pa2.id = me.a2
            JOIN players pb1 ON pb1.id = me.b1
            JOIN players pb2 ON pb2.id = me.b2
            ORDER BY elo_gap DESC
            LIMIT ?
            """,
            [limit],
        ).df()

    def event_strength_of_schedule(self, event_id: int) -> pd.DataFrame:
        """
        Average opponent Elo faced per attendee in this event.
        """
        return self.conn.execute(
            """
            WITH appearances AS (
                SELECT
                    ta.player1_id AS player_id,
                    tb.player1_id AS opp1,
                    tb.player2_id AS opp2
                FROM matches m
                JOIN scores s ON s.match_id = m.id
                JOIN teams ta ON ta.id = m.team_a_id
                JOIN teams tb ON tb.id = m.team_b_id
                WHERE m.event_id = ? AND m.status = 'completed'
                UNION ALL
                SELECT ta.player2_id, tb.player1_id, tb.player2_id
                FROM matches m
                JOIN scores s ON s.match_id = m.id
                JOIN teams ta ON ta.id = m.team_a_id
                JOIN teams tb ON tb.id = m.team_b_id
                WHERE m.event_id = ? AND m.status = 'completed'
                UNION ALL
                SELECT tb.player1_id, ta.player1_id, ta.player2_id
                FROM matches m
                JOIN scores s ON s.match_id = m.id
                JOIN teams ta ON ta.id = m.team_a_id
                JOIN teams tb ON tb.id = m.team_b_id
                WHERE m.event_id = ? AND m.status = 'completed'
                UNION ALL
                SELECT tb.player2_id, ta.player1_id, ta.player2_id
                FROM matches m
                JOIN scores s ON s.match_id = m.id
                JOIN teams ta ON ta.id = m.team_a_id
                JOIN teams tb ON tb.id = m.team_b_id
                WHERE m.event_id = ? AND m.status = 'completed'
            ),
            expanded AS (
                SELECT player_id, opp1 AS opponent_id FROM appearances
                UNION ALL
                SELECT player_id, opp2 AS opponent_id FROM appearances
            )
            SELECT
                ep.player_id,
                COALESCE(p.display_name, p.name) AS player,
                COUNT(ex.opponent_id) AS opponent_samples,
                AVG(op.current_elo) AS strength_of_schedule
            FROM event_players ep
            JOIN players p ON p.id = ep.player_id
            LEFT JOIN expanded ex ON ex.player_id = ep.player_id
            LEFT JOIN players op ON op.id = ex.opponent_id
            WHERE ep.event_id = ?
            GROUP BY ep.player_id, COALESCE(p.display_name, p.name)
            ORDER BY strength_of_schedule DESC NULLS LAST, lower(COALESCE(p.display_name, p.name))
            """,
            [event_id, event_id, event_id, event_id, event_id],
        ).df()

    def event_player_rolling_metrics(self, event_id: int) -> pd.DataFrame:
        """
        Per-player rolling metrics across completed matches in an event:
        - rolling_point_diff: cumulative point differential
        - rolling_elo_gain: cumulative Elo delta
        """
        df = self.conn.execute(
            """
            WITH player_matches AS (
                SELECT
                    m.id AS match_id,
                    m.match_order,
                    ta.player1_id AS player_id,
                    (s.team_a_score - s.team_b_score) AS point_diff
                FROM matches m
                JOIN scores s ON s.match_id = m.id
                JOIN teams ta ON ta.id = m.team_a_id
                WHERE m.event_id = ? AND m.status = 'completed'
                UNION ALL
                SELECT
                    m.id AS match_id,
                    m.match_order,
                    ta.player2_id AS player_id,
                    (s.team_a_score - s.team_b_score) AS point_diff
                FROM matches m
                JOIN scores s ON s.match_id = m.id
                JOIN teams ta ON ta.id = m.team_a_id
                WHERE m.event_id = ? AND m.status = 'completed'
                UNION ALL
                SELECT
                    m.id AS match_id,
                    m.match_order,
                    tb.player1_id AS player_id,
                    (s.team_b_score - s.team_a_score) AS point_diff
                FROM matches m
                JOIN scores s ON s.match_id = m.id
                JOIN teams tb ON tb.id = m.team_b_id
                WHERE m.event_id = ? AND m.status = 'completed'
                UNION ALL
                SELECT
                    m.id AS match_id,
                    m.match_order,
                    tb.player2_id AS player_id,
                    (s.team_b_score - s.team_a_score) AS point_diff
                FROM matches m
                JOIN scores s ON s.match_id = m.id
                JOIN teams tb ON tb.id = m.team_b_id
                WHERE m.event_id = ? AND m.status = 'completed'
            )
            SELECT
                pm.match_id,
                pm.match_order,
                pm.player_id,
                COALESCE(p.display_name, p.name) AS player,
                pm.point_diff,
                COALESCE(eh.delta, 0.0) AS elo_delta
            FROM player_matches pm
            JOIN players p ON p.id = pm.player_id
            LEFT JOIN elo_history eh
                ON eh.match_id = pm.match_id
               AND eh.player_id = pm.player_id
               AND eh.event_id = ?
            ORDER BY pm.match_order, pm.match_id, lower(COALESCE(p.display_name, p.name))
            """,
            [event_id, event_id, event_id, event_id, event_id],
        ).df()
        if df.empty:
            return df
        df["rolling_point_diff"] = df.groupby("player_id")["point_diff"].cumsum()
        df["rolling_elo_gain"] = df.groupby("player_id")["elo_delta"].cumsum()
        return df

    def event_attendee_win_loss(self, event_id: int) -> pd.DataFrame:
        return self.conn.execute(
            """
            SELECT
                es.player_id,
                COALESCE(p.display_name, p.name) AS player,
                es.wins,
                es.losses
            FROM event_standings es
            JOIN players p ON p.id = es.player_id
            WHERE es.event_id = ?
            ORDER BY lower(COALESCE(p.display_name, p.name))
            """,
            [event_id],
        ).df()

    def event_attendee_point_diff_heatmap(self, event_id: int) -> pd.DataFrame:
        """
        Return long-form rows of avg point differential for player vs opponent
        within a single event's completed matches.
        """
        return self.conn.execute(
            """
            WITH match_rows AS (
                SELECT
                    ta.player1_id AS a1,
                    ta.player2_id AS a2,
                    tb.player1_id AS b1,
                    tb.player2_id AS b2,
                    s.team_a_score AS sa,
                    s.team_b_score AS sb
                FROM matches m
                JOIN scores s ON s.match_id = m.id
                JOIN teams ta ON ta.id = m.team_a_id
                JOIN teams tb ON tb.id = m.team_b_id
                WHERE m.event_id = ? AND m.status = 'completed'
            ),
            player_vs AS (
                SELECT a1 AS player_id, b1 AS opponent_id, (sa - sb) AS point_diff FROM match_rows
                UNION ALL
                SELECT a1, b2, (sa - sb) FROM match_rows
                UNION ALL
                SELECT a2, b1, (sa - sb) FROM match_rows
                UNION ALL
                SELECT a2, b2, (sa - sb) FROM match_rows
                UNION ALL
                SELECT b1, a1, (sb - sa) FROM match_rows
                UNION ALL
                SELECT b1, a2, (sb - sa) FROM match_rows
                UNION ALL
                SELECT b2, a1, (sb - sa) FROM match_rows
                UNION ALL
                SELECT b2, a2, (sb - sa) FROM match_rows
            )
            SELECT
                pv.player_id,
                COALESCE(pp.display_name, pp.name) AS player,
                pv.opponent_id,
                COALESCE(op.display_name, op.name) AS opponent,
                COUNT(*) AS games,
                AVG(pv.point_diff) AS avg_point_diff
            FROM player_vs pv
            JOIN event_players ep1 ON ep1.event_id = ? AND ep1.player_id = pv.player_id
            JOIN event_players ep2 ON ep2.event_id = ? AND ep2.player_id = pv.opponent_id
            JOIN players pp ON pp.id = pv.player_id
            JOIN players op ON op.id = pv.opponent_id
            GROUP BY
                pv.player_id,
                COALESCE(pp.display_name, pp.name),
                pv.opponent_id,
                COALESCE(op.display_name, op.name)
            ORDER BY lower(COALESCE(pp.display_name, pp.name)), lower(COALESCE(op.display_name, op.name))
            """,
            [event_id, event_id, event_id],
        ).df()

    def all_time_player_match_rows(
        self,
        *,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> pd.DataFrame:
        where = ["m.status = 'completed'"]
        params: list[object] = []
        if start_date:
            where.append("CAST(e.event_date AS DATE) >= ?")
            params.append(start_date)
        if end_date:
            where.append("CAST(e.event_date AS DATE) <= ?")
            params.append(end_date)

        return self.conn.execute(
            f"""
            WITH base AS (
                SELECT
                    m.id AS match_id,
                    m.event_id,
                    m.match_order,
                    CAST(e.event_date AS DATE) AS event_date,
                    m.team_a_id,
                    m.team_b_id,
                    ta.player1_id AS a1, ta.player2_id AS a2,
                    tb.player1_id AS b1, tb.player2_id AS b2,
                    s.team_a_score, s.team_b_score, s.winner_team_id
                FROM matches m
                JOIN events e ON e.id = m.event_id
                JOIN scores s ON s.match_id = m.id
                JOIN teams ta ON ta.id = m.team_a_id
                JOIN teams tb ON tb.id = m.team_b_id
                WHERE {" AND ".join(where)}
            ),
            elo_joined AS (
                SELECT
                    b.*,
                    eh_a1.elo_before AS a1_elo_before, eh_a1.delta AS a1_delta,
                    eh_a2.elo_before AS a2_elo_before, eh_a2.delta AS a2_delta,
                    eh_b1.elo_before AS b1_elo_before, eh_b1.delta AS b1_delta,
                    eh_b2.elo_before AS b2_elo_before, eh_b2.delta AS b2_delta
                FROM base b
                LEFT JOIN elo_history eh_a1 ON eh_a1.match_id = b.match_id AND eh_a1.player_id = b.a1
                LEFT JOIN elo_history eh_a2 ON eh_a2.match_id = b.match_id AND eh_a2.player_id = b.a2
                LEFT JOIN elo_history eh_b1 ON eh_b1.match_id = b.match_id AND eh_b1.player_id = b.b1
                LEFT JOIN elo_history eh_b2 ON eh_b2.match_id = b.match_id AND eh_b2.player_id = b.b2
            )
            SELECT *
            FROM (
                SELECT
                    ej.match_id,
                    ej.event_id,
                    ej.event_date,
                    ej.match_order,
                    ej.a1 AS player_id,
                    ej.a2 AS partner_id,
                    COALESCE(p_a1.display_name, p_a1.name) AS player,
                    COALESCE(p_a2.display_name, p_a2.name) AS partner_name,
                    COALESCE(p_b1.display_name, p_b1.name) AS opp1_name,
                    COALESCE(p_b2.display_name, p_b2.name) AS opp2_name,
                    TRUE AS team_a_side,
                    (ej.winner_team_id = ej.team_a_id) AS won,
                    ej.team_a_score AS points_for,
                    ej.team_b_score AS points_against,
                    (ej.team_a_score - ej.team_b_score) AS point_diff,
                    COALESCE(ej.a1_delta, 0.0) AS elo_delta,
                    COALESCE(ej.a1_elo_before, 1000.0) AS player_elo_before,
                    ((COALESCE(ej.a1_elo_before, 1000.0) + COALESCE(ej.a2_elo_before, 1000.0)) / 2.0) AS team_avg_elo_before,
                    ((COALESCE(ej.b1_elo_before, 1000.0) + COALESCE(ej.b2_elo_before, 1000.0)) / 2.0) AS opp_avg_elo_before
                FROM elo_joined ej
                JOIN players p_a1 ON p_a1.id = ej.a1
                JOIN players p_a2 ON p_a2.id = ej.a2
                JOIN players p_b1 ON p_b1.id = ej.b1
                JOIN players p_b2 ON p_b2.id = ej.b2
                UNION ALL
                SELECT
                    ej.match_id, ej.event_id, ej.event_date, ej.match_order,
                    ej.a2, ej.a1,
                    COALESCE(p_a2.display_name, p_a2.name),
                    COALESCE(p_a1.display_name, p_a1.name),
                    COALESCE(p_b1.display_name, p_b1.name),
                    COALESCE(p_b2.display_name, p_b2.name),
                    TRUE,
                    (ej.winner_team_id = ej.team_a_id),
                    ej.team_a_score, ej.team_b_score, (ej.team_a_score - ej.team_b_score),
                    COALESCE(ej.a2_delta, 0.0),
                    COALESCE(ej.a2_elo_before, 1000.0),
                    ((COALESCE(ej.a1_elo_before, 1000.0) + COALESCE(ej.a2_elo_before, 1000.0)) / 2.0),
                    ((COALESCE(ej.b1_elo_before, 1000.0) + COALESCE(ej.b2_elo_before, 1000.0)) / 2.0)
                FROM elo_joined ej
                JOIN players p_a1 ON p_a1.id = ej.a1
                JOIN players p_a2 ON p_a2.id = ej.a2
                JOIN players p_b1 ON p_b1.id = ej.b1
                JOIN players p_b2 ON p_b2.id = ej.b2
                UNION ALL
                SELECT
                    ej.match_id, ej.event_id, ej.event_date, ej.match_order,
                    ej.b1, ej.b2,
                    COALESCE(p_b1.display_name, p_b1.name),
                    COALESCE(p_b2.display_name, p_b2.name),
                    COALESCE(p_a1.display_name, p_a1.name),
                    COALESCE(p_a2.display_name, p_a2.name),
                    FALSE,
                    (ej.winner_team_id = ej.team_b_id),
                    ej.team_b_score, ej.team_a_score, (ej.team_b_score - ej.team_a_score),
                    COALESCE(ej.b1_delta, 0.0),
                    COALESCE(ej.b1_elo_before, 1000.0),
                    ((COALESCE(ej.b1_elo_before, 1000.0) + COALESCE(ej.b2_elo_before, 1000.0)) / 2.0),
                    ((COALESCE(ej.a1_elo_before, 1000.0) + COALESCE(ej.a2_elo_before, 1000.0)) / 2.0)
                FROM elo_joined ej
                JOIN players p_a1 ON p_a1.id = ej.a1
                JOIN players p_a2 ON p_a2.id = ej.a2
                JOIN players p_b1 ON p_b1.id = ej.b1
                JOIN players p_b2 ON p_b2.id = ej.b2
                UNION ALL
                SELECT
                    ej.match_id, ej.event_id, ej.event_date, ej.match_order,
                    ej.b2, ej.b1,
                    COALESCE(p_b2.display_name, p_b2.name),
                    COALESCE(p_b1.display_name, p_b1.name),
                    COALESCE(p_a1.display_name, p_a1.name),
                    COALESCE(p_a2.display_name, p_a2.name),
                    FALSE,
                    (ej.winner_team_id = ej.team_b_id),
                    ej.team_b_score, ej.team_a_score, (ej.team_b_score - ej.team_a_score),
                    COALESCE(ej.b2_delta, 0.0),
                    COALESCE(ej.b2_elo_before, 1000.0),
                    ((COALESCE(ej.b1_elo_before, 1000.0) + COALESCE(ej.b2_elo_before, 1000.0)) / 2.0),
                    ((COALESCE(ej.a1_elo_before, 1000.0) + COALESCE(ej.a2_elo_before, 1000.0)) / 2.0)
                FROM elo_joined ej
                JOIN players p_a1 ON p_a1.id = ej.a1
                JOIN players p_a2 ON p_a2.id = ej.a2
                JOIN players p_b1 ON p_b1.id = ej.b1
                JOIN players p_b2 ON p_b2.id = ej.b2
            ) AS all_rows
            ORDER BY event_date, match_order, match_id, lower(player)
            """,
            params,
        ).df()

    def all_time_player_snapshot(
        self,
        *,
        start_date: str | None = None,
        end_date: str | None = None,
        min_games: int = 1,
    ) -> pd.DataFrame:
        rows = self.all_time_player_match_rows(start_date=start_date, end_date=end_date)
        if rows.empty:
            return rows

        rows["won_int"] = rows["won"].astype(int)
        grouped = (
            rows.groupby(["player_id", "player"], as_index=False)
            .agg(
                games=("match_id", "count"),
                wins=("won_int", "sum"),
                points_for=("points_for", "sum"),
                points_against=("points_against", "sum"),
                point_diff=("point_diff", "sum"),
                avg_margin=("point_diff", "mean"),
                avg_points_scored=("points_for", "mean"),
                avg_points_allowed=("points_against", "mean"),
                strength_of_schedule=("opp_avg_elo_before", "mean"),
                partner_diversity=("partner_id", "nunique"),
            )
        )
        grouped["losses"] = grouped["games"] - grouped["wins"]
        grouped["win_pct"] = grouped["wins"] / grouped["games"]

        grouped["avg_margin_victory"] = (
            rows[rows["won"]]
            .groupby("player_id")["point_diff"]
            .mean()
            .reindex(grouped["player_id"])
            .to_numpy()
        )
        grouped["avg_margin_defeat"] = (
            rows[~rows["won"]]
            .assign(loss_margin=lambda d: d["point_diff"].abs())
            .groupby("player_id")["loss_margin"]
            .mean()
            .reindex(grouped["player_id"])
            .to_numpy()
        )

        rows["expected_win_prob"] = 1.0 / (
            1.0 + 10 ** ((rows["opp_avg_elo_before"] - rows["team_avg_elo_before"]) / 400.0)
        )
        grouped["strength_of_victory"] = (
            rows[rows["won"]]
            .groupby("player_id")["opp_avg_elo_before"]
            .mean()
            .reindex(grouped["player_id"])
            .to_numpy()
        )
        grouped["upset_wins"] = (
            rows[(rows["won"]) & (rows["expected_win_prob"] < 0.5)]
            .groupby("player_id")["match_id"]
            .count()
            .reindex(grouped["player_id"], fill_value=0)
            .to_numpy()
        )
        grouped["upset_losses"] = (
            rows[(~rows["won"]) & (rows["expected_win_prob"] >= 0.5)]
            .groupby("player_id")["match_id"]
            .count()
            .reindex(grouped["player_id"], fill_value=0)
            .to_numpy()
        )
        grouped["close_game_record"] = (
            rows[rows["point_diff"].abs() <= 2]
            .groupby("player_id")["won_int"]
            .sum()
            .reindex(grouped["player_id"], fill_value=0)
            .to_numpy()
        )
        grouped["close_games"] = (
            rows[rows["point_diff"].abs() <= 2]
            .groupby("player_id")["match_id"]
            .count()
            .reindex(grouped["player_id"], fill_value=0)
            .to_numpy()
        )
        grouped["blowout_wins"] = (
            rows[(rows["won"]) & (rows["point_diff"] >= 6)]
            .groupby("player_id")["match_id"]
            .count()
            .reindex(grouped["player_id"], fill_value=0)
            .to_numpy()
        )
        grouped["blowout_losses"] = (
            rows[(~rows["won"]) & (rows["point_diff"] <= -6)]
            .groupby("player_id")["match_id"]
            .count()
            .reindex(grouped["player_id"], fill_value=0)
            .to_numpy()
        )
        grouped["consistency_score"] = (
            100.0
            - rows.groupby("player_id")["point_diff"]
            .std()
            .fillna(0.0)
            .mul(7.5)
            .reindex(grouped["player_id"], fill_value=100.0)
            .to_numpy()
        ).clip(0.0, 100.0)

        current_elos = self.conn.execute(
            "SELECT id AS player_id, current_elo FROM players"
        ).df()
        grouped = grouped.merge(current_elos, on="player_id", how="left")

        rows_sorted = rows.sort_values(["event_date", "match_id", "player_id"])
        recent_delta = (
            rows_sorted.groupby("player_id")
            .tail(10)
            .groupby("player_id")["elo_delta"]
            .sum()
            .reindex(grouped["player_id"], fill_value=0.0)
            .to_numpy()
        )
        grouped["elo_delta_last_10"] = recent_delta

        streaks: dict[int, tuple[int, int]] = {}
        for player_id, player_rows in rows_sorted.groupby("player_id"):
            outcomes = player_rows["won"].tolist()
            longest = 0
            current = 0
            sign = 1
            last_sign = 1
            for won in outcomes:
                sgn = 1 if bool(won) else -1
                if sgn == sign:
                    current += 1
                else:
                    sign = sgn
                    current = 1
                if sgn == 1:
                    longest = max(longest, current)
                last_sign = sgn
            current_signed = current * last_sign if outcomes else 0
            streaks[int(player_id)] = (current_signed, longest)
        grouped["current_streak"] = grouped["player_id"].map(lambda i: streaks.get(int(i), (0, 0))[0])
        grouped["longest_win_streak"] = grouped["player_id"].map(lambda i: streaks.get(int(i), (0, 0))[1])

        grouped = grouped[grouped["games"] >= max(1, int(min_games))].copy()
        grouped = grouped.sort_values(
            ["current_elo", "win_pct", "wins", "point_diff"],
            ascending=[False, False, False, False],
        ).reset_index(drop=True)
        grouped["rank"] = grouped.index + 1
        return grouped

    def all_time_player_progress(
        self,
        *,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> pd.DataFrame:
        rows = self.all_time_player_match_rows(start_date=start_date, end_date=end_date)
        if rows.empty:
            return rows
        rows = rows.sort_values(["player_id", "event_date", "match_id"]).copy()
        rows["wins_cum"] = rows.groupby("player_id")["won"].cumsum()
        rows["games_cum"] = rows.groupby("player_id").cumcount() + 1
        rows["win_pct_cum"] = rows["wins_cum"] / rows["games_cum"]
        rows["rolling_win_pct"] = rows.groupby("player_id")["won"].transform(
            lambda s: s.rolling(5, min_periods=1).mean()
        )
        rows["rolling_point_diff"] = rows.groupby("player_id")["point_diff"].transform(
            lambda s: s.rolling(5, min_periods=1).mean()
        )
        rows["rolling_elo_gain"] = rows.groupby("player_id")["elo_delta"].transform(
            lambda s: s.rolling(5, min_periods=1).sum()
        )
        rows["elo_cum_gain"] = rows.groupby("player_id")["elo_delta"].cumsum()
        rows["elo_over_time"] = rows["player_elo_before"] + rows["elo_delta"]
        rows["avg_margin_over_time"] = (
            rows.groupby("player_id")["point_diff"].cumsum() / rows["games_cum"]
        )
        return rows

    def all_time_games_by_week(
        self,
        *,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> pd.DataFrame:
        where = ["m.status = 'completed'"]
        params: list[object] = []
        if start_date:
            where.append("CAST(e.event_date AS DATE) >= ?")
            params.append(start_date)
        if end_date:
            where.append("CAST(e.event_date AS DATE) <= ?")
            params.append(end_date)
        return self.conn.execute(
            f"""
            SELECT
                DATE_TRUNC('week', CAST(e.event_date AS DATE)) AS week_start,
                COUNT(*) AS games_played
            FROM matches m
            JOIN events e ON e.id = m.event_id
            WHERE {" AND ".join(where)}
            GROUP BY 1
            ORDER BY 1
            """,
            params,
        ).df()

    def live_event_player_metrics(self, event_id: int) -> pd.DataFrame:
        rows = self.all_time_player_match_rows().query("event_id == @event_id").copy()
        if rows.empty:
            return rows
        grouped = (
            rows.groupby(["player_id", "player"], as_index=False)
            .agg(
                games=("match_id", "count"),
                wins=("won", "sum"),
                points_for=("points_for", "sum"),
                points_against=("points_against", "sum"),
                point_diff=("point_diff", "sum"),
                elo_delta_tonight=("elo_delta", "sum"),
                strength_of_schedule=("opp_avg_elo_before", "mean"),
            )
        )
        grouped["wins"] = grouped["wins"].astype(int)
        grouped["losses"] = grouped["games"] - grouped["wins"]
        grouped["win_pct"] = grouped["wins"] / grouped["games"]
        grouped["strength_of_schedule"] = grouped["strength_of_schedule"].fillna(1000.0)
        grouped["avg_win_margin"] = (
            rows[rows["won"]]
            .groupby("player_id")["point_diff"]
            .mean()
            .reindex(grouped["player_id"])
            .fillna(0.0)
            .to_numpy()
        )
        grouped["power_score"] = (
            grouped["win_pct"] * 60.0
            + (grouped["point_diff"] / grouped["games"].clip(lower=1)) * 4.0
            + grouped["elo_delta_tonight"] * 1.2
            + grouped["wins"] * 2.0
        )
        grouped = grouped.sort_values(
            ["power_score", "wins", "point_diff", "elo_delta_tonight"],
            ascending=[False, False, False, False],
        ).reset_index(drop=True)
        grouped["rank"] = grouped.index + 1

        rows_sorted = rows.sort_values(["match_order", "match_id"])
        current_streaks: dict[int, int] = {}
        momentum: dict[int, str] = {}
        for pid, player_rows in rows_sorted.groupby("player_id"):
            outcomes = ["W" if bool(v) else "L" for v in player_rows["won"].tolist()]
            # Most recent first for display.
            last5 = list(reversed(outcomes[-5:]))
            momentum[int(pid)] = "".join(last5)
            cur = 0
            sign = "W"
            for out in outcomes:
                if out == sign:
                    cur += 1
                else:
                    sign = out
                    cur = 1
            current_streaks[int(pid)] = cur if sign == "W" else -cur
        grouped["current_streak"] = grouped["player_id"].map(current_streaks).fillna(0).astype(int)
        grouped["momentum"] = grouped["player_id"].map(momentum).fillna("")

        # Rank movement vs previous completed match snapshot.
        match_ids = rows_sorted["match_id"].drop_duplicates().tolist()
        prev_rank_by_player: dict[int, int] = {}
        if len(match_ids) >= 2:
            prev_rows = rows_sorted[rows_sorted["match_id"] != match_ids[-1]].copy()
            if not prev_rows.empty:
                prev = (
                    prev_rows.groupby(["player_id"], as_index=False)
                    .agg(
                        games=("match_id", "count"),
                        wins=("won", "sum"),
                        point_diff=("point_diff", "sum"),
                        elo_delta_tonight=("elo_delta", "sum"),
                    )
                )
                prev["wins"] = prev["wins"].astype(int)
                prev["win_pct"] = prev["wins"] / prev["games"]
                prev["power_score"] = (
                    prev["win_pct"] * 60.0
                    + (prev["point_diff"] / prev["games"].clip(lower=1)) * 4.0
                    + prev["elo_delta_tonight"] * 1.2
                    + prev["wins"] * 2.0
                )
                prev = prev.sort_values(
                    ["power_score", "wins", "point_diff", "elo_delta_tonight"],
                    ascending=[False, False, False, False],
                ).reset_index(drop=True)
                prev["prev_rank"] = prev.index + 1
                prev_rank_by_player = {
                    int(r["player_id"]): int(r["prev_rank"]) for _, r in prev.iterrows()
                }
        grouped["prev_rank"] = grouped["player_id"].map(prev_rank_by_player)
        grouped["rank_delta"] = grouped.apply(
            lambda r: (int(r["prev_rank"]) - int(r["rank"])) if pd.notna(r["prev_rank"]) else 0,
            axis=1,
        )
        return grouped

    def live_event_biggest_upset(self, event_id: int) -> dict | None:
        df = self.conn.execute(
            """
            WITH base AS (
                SELECT
                    m.id AS match_id,
                    m.match_order,
                    m.team_a_id,
                    m.team_b_id,
                    ta.player1_id AS a1, ta.player2_id AS a2,
                    tb.player1_id AS b1, tb.player2_id AS b2,
                    s.team_a_score, s.team_b_score, s.winner_team_id
                FROM matches m
                JOIN scores s ON s.match_id = m.id
                JOIN teams ta ON ta.id = m.team_a_id
                JOIN teams tb ON tb.id = m.team_b_id
                WHERE m.event_id = ? AND m.status = 'completed'
            )
            SELECT
                b.match_id,
                b.match_order,
                COALESCE(pa1.display_name, pa1.name) AS a1_name,
                COALESCE(pa2.display_name, pa2.name) AS a2_name,
                COALESCE(pb1.display_name, pb1.name) AS b1_name,
                COALESCE(pb2.display_name, pb2.name) AS b2_name,
                b.team_a_score, b.team_b_score,
                b.winner_team_id,
                b.team_a_id, b.team_b_id,
                ((COALESCE(eh_a1.elo_before, 1000.0) + COALESCE(eh_a2.elo_before, 1000.0)) / 2.0) AS team_a_elo_before,
                ((COALESCE(eh_b1.elo_before, 1000.0) + COALESCE(eh_b2.elo_before, 1000.0)) / 2.0) AS team_b_elo_before
            FROM base b
            JOIN players pa1 ON pa1.id = b.a1
            JOIN players pa2 ON pa2.id = b.a2
            JOIN players pb1 ON pb1.id = b.b1
            JOIN players pb2 ON pb2.id = b.b2
            LEFT JOIN elo_history eh_a1 ON eh_a1.match_id = b.match_id AND eh_a1.player_id = b.a1
            LEFT JOIN elo_history eh_a2 ON eh_a2.match_id = b.match_id AND eh_a2.player_id = b.a2
            LEFT JOIN elo_history eh_b1 ON eh_b1.match_id = b.match_id AND eh_b1.player_id = b.b1
            LEFT JOIN elo_history eh_b2 ON eh_b2.match_id = b.match_id AND eh_b2.player_id = b.b2
            """,
            [event_id],
        ).df()
        if df.empty:
            return None
        df["winner_is_a"] = df["winner_team_id"] == df["team_a_id"]
        df["winner_elo_before"] = df.apply(
            lambda r: r["team_a_elo_before"] if r["winner_is_a"] else r["team_b_elo_before"], axis=1
        )
        df["loser_elo_before"] = df.apply(
            lambda r: r["team_b_elo_before"] if r["winner_is_a"] else r["team_a_elo_before"], axis=1
        )
        df["upset_gap"] = df["loser_elo_before"] - df["winner_elo_before"]
        upsets = df[df["upset_gap"] > 0].sort_values("upset_gap", ascending=False)
        if upsets.empty:
            return None
        top = upsets.iloc[0].to_dict()
        return {
            "match_id": int(top["match_id"]),
            "match_order": int(top["match_order"]),
            "team_a": f"{top['a1_name']} / {top['a2_name']}",
            "team_b": f"{top['b1_name']} / {top['b2_name']}",
            "score": f"{int(top['team_a_score'])}-{int(top['team_b_score'])}",
            "upset_gap": float(top["upset_gap"]),
        }

    def live_event_closest_match(self, event_id: int) -> dict | None:
        row = self.conn.execute(
            """
            SELECT
                m.id AS match_id,
                m.match_order,
                COALESCE(pa1.display_name, pa1.name) || ' / ' || COALESCE(pa2.display_name, pa2.name) AS team_a,
                COALESCE(pb1.display_name, pb1.name) || ' / ' || COALESCE(pb2.display_name, pb2.name) AS team_b,
                s.team_a_score,
                s.team_b_score,
                ABS(s.team_a_score - s.team_b_score) AS margin
            FROM matches m
            JOIN scores s ON s.match_id = m.id
            JOIN teams ta ON ta.id = m.team_a_id
            JOIN teams tb ON tb.id = m.team_b_id
            JOIN players pa1 ON pa1.id = ta.player1_id
            JOIN players pa2 ON pa2.id = ta.player2_id
            JOIN players pb1 ON pb1.id = tb.player1_id
            JOIN players pb2 ON pb2.id = tb.player2_id
            WHERE m.event_id = ? AND m.status = 'completed'
            ORDER BY margin ASC, m.match_order DESC
            LIMIT 1
            """,
            [event_id],
        ).fetchone()
        if row is None:
            return None
        return {
            "match_id": int(row[0]),
            "match_order": int(row[1]),
            "team_a": str(row[2]),
            "team_b": str(row[3]),
            "score": f"{int(row[4])}-{int(row[5])}",
            "margin": int(row[6]),
        }

    def live_event_scatter(self, event_id: int) -> pd.DataFrame:
        live = self.live_event_player_metrics(event_id)
        if live.empty:
            return live
        return live[
            [
                "player_id",
                "player",
                "win_pct",
                "elo_delta_tonight",
                "strength_of_schedule",
                "point_diff",
                "wins",
                "losses",
                "games",
            ]
        ].copy()

    def all_time_point_diff_heatmap(
        self,
        *,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> pd.DataFrame:
        rows = self.all_time_player_match_rows(start_date=start_date, end_date=end_date)
        if rows.empty:
            return rows

        opponent_rows = rows[["match_id", "player_id", "player", "point_diff"]].merge(
            rows[["match_id", "player_id", "player"]],
            on="match_id",
            suffixes=("", "_opp"),
        )
        opponent_rows = opponent_rows[opponent_rows["player_id"] != opponent_rows["player_id_opp"]].copy()
        return (
            opponent_rows.groupby(
                ["player_id", "player", "player_id_opp", "player_opp"], as_index=False
            )
            .agg(
                games=("match_id", "count"),
                avg_point_diff=("point_diff", "mean"),
                win_pct=("point_diff", lambda s: float((s > 0).mean())),
            )
            .rename(columns={"player_id_opp": "opponent_id", "player_opp": "opponent"})
        )
