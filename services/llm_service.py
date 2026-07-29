"""Local LLM orchestration with Ollama."""

from __future__ import annotations

import duckdb

from database.connection import get_connection
from llm.client import OllamaClient
from llm.prompts import event_recap_prompt
from utils.config import OLLAMA_MODEL, OLLAMA_URL


class LlmService:
    def __init__(self, conn: duckdb.DuckDBPyConnection | None = None) -> None:
        self.conn = conn or get_connection()
        self.client = OllamaClient(OLLAMA_URL, OLLAMA_MODEL)

    def generate_event_recap(self, event_id: int) -> str:
        event = self.conn.execute(
            "SELECT name, event_date FROM events WHERE id = ?",
            [event_id],
        ).fetchone()
        if not event:
            return "Event not found."
        standings = self.conn.execute(
            """
            SELECT
                COALESCE(p.display_name, p.name) AS player,
                es.wins,
                es.losses,
                ROUND(es.win_pct * 100, 1) AS win_pct,
                ROUND(es.point_diff, 1) AS point_diff,
                es.current_streak,
                ROUND(es.elo, 1) AS elo
            FROM event_standings es
            JOIN players p ON p.id = es.player_id
            WHERE es.event_id = ?
            ORDER BY es.wins DESC, es.point_diff DESC, es.elo DESC
            """,
            [event_id],
        ).fetchdf()
        if standings.empty:
            return "No standings data yet for this event."

        standings_block = standings.to_string(index=False)
        prompt = event_recap_prompt(str(event[0]), str(event[1]), standings_block)
        text = self._normalize_recap(self.client.generate(prompt))

        self.conn.execute(
            """
            INSERT INTO app_meta (key, value)
            VALUES (?, ?)
            ON CONFLICT (key) DO UPDATE SET value = excluded.value
            """,
            [f"event_recap_{event_id}", text],
        )
        return text

    @staticmethod
    def _normalize_recap(text: str) -> str:
        """Keep at most 3 non-empty lines, separated by blank lines."""
        lines = [ln.strip() for ln in str(text or "").splitlines() if ln.strip()]
        return "\n\n".join(lines[:3])

    def get_saved_event_recap(self, event_id: int) -> str | None:
        row = self.conn.execute(
            "SELECT value FROM app_meta WHERE key = ?",
            [f"event_recap_{event_id}"],
        ).fetchone()
        if not row or not row[0]:
            return None
        return self._normalize_recap(str(row[0]))

    def live_commentary_feed(self, event_id: int, limit: int = 6) -> list[str]:
        matches = self.conn.execute(
            """
            SELECT
                m.id AS match_id,
                m.match_order,
                COALESCE(pa1.display_name, pa1.name) || ' / ' || COALESCE(pa2.display_name, pa2.name) AS team_a,
                COALESCE(pb1.display_name, pb1.name) || ' / ' || COALESCE(pb2.display_name, pb2.name) AS team_b,
                s.team_a_score,
                s.team_b_score
            FROM matches m
            JOIN scores s ON s.match_id = m.id
            JOIN teams ta ON ta.id = m.team_a_id
            JOIN teams tb ON tb.id = m.team_b_id
            JOIN players pa1 ON pa1.id = ta.player1_id
            JOIN players pa2 ON pa2.id = ta.player2_id
            JOIN players pb1 ON pb1.id = tb.player1_id
            JOIN players pb2 ON pb2.id = tb.player2_id
            WHERE m.event_id = ? AND m.status = 'completed'
            ORDER BY m.match_order DESC, m.id DESC
            LIMIT ?
            """,
            [event_id, max(1, int(limit))],
        ).fetchdf()
        if matches.empty:
            return ["Waiting for the first completed match tonight."]

        standings = self.conn.execute(
            """
            SELECT
                COALESCE(p.display_name, p.name) AS player,
                es.wins,
                es.losses,
                es.point_diff
            FROM event_standings es
            JOIN players p ON p.id = es.player_id
            WHERE es.event_id = ?
            ORDER BY es.wins DESC, es.point_diff DESC, es.elo DESC
            """,
            [event_id],
        ).fetchdf()
        leader = None
        if not standings.empty:
            top = standings.iloc[0]
            leader = f"{top['player']} ({int(top['wins'])}-{int(top['losses'])}, {int(top['point_diff']):+d})"

        lines: list[str] = []
        for _, row in matches.iterrows():
            score = f"{int(row['team_a_score'])}-{int(row['team_b_score'])}"
            margin = abs(int(row["team_a_score"]) - int(row["team_b_score"]))
            winner = row["team_a"] if int(row["team_a_score"]) > int(row["team_b_score"]) else row["team_b"]
            if margin <= 2:
                line = f"{winner} edges a tight one, {score}."
            elif margin >= 6:
                line = f"{winner} dominates with a {score} result."
            else:
                line = f"{winner} takes it {score}."
            if leader:
                line = f"{line} Current leader: {leader}."
            lines.append(line)
        return lines
