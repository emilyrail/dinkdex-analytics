"""Score submit, edit, and undo."""

from __future__ import annotations

import json

import duckdb

from database.connection import get_connection
from models.enums import MatchStatus
from models.match import Match
from models.score import Score
from repositories.matches import MatchRepository, TeamRepository
from repositories.scores import ScoreRepository
from services.recompute_service import RecomputeService


class ScoreValidationError(ValueError):
    pass


class ScoreService:
    def __init__(self, conn: duckdb.DuckDBPyConnection | None = None) -> None:
        self.conn = conn or get_connection()
        self.matches = MatchRepository(self.conn)
        self.scores = ScoreRepository(self.conn)
        self.teams = TeamRepository(self.conn)
        self.recompute = RecomputeService(self.conn)

    def next_match(self, event_id: int) -> Match | None:
        return self.matches.next_scheduled(event_id)

    def validate_score(
        self,
        team_a_score: int,
        team_b_score: int,
        *,
        game_to: int = 11,
        win_by: int = 2,
        strict: bool = True,
    ) -> None:
        if team_a_score < 0 or team_b_score < 0:
            raise ScoreValidationError("Scores cannot be negative")
        if team_a_score == team_b_score:
            raise ScoreValidationError("Scores cannot be tied")
        winner = max(team_a_score, team_b_score)
        loser = min(team_a_score, team_b_score)
        if not strict:
            return
        if winner < game_to:
            raise ScoreValidationError(f"Winner must reach at least {game_to}")
        if winner > game_to and (winner - loser) < win_by:
            raise ScoreValidationError(f"Must win by {win_by}")
        if winner == game_to and (winner - loser) < win_by and loser >= game_to - 1:
            # e.g. 11-10 invalid
            raise ScoreValidationError(f"Must win by {win_by}")
        if winner > game_to and (winner - loser) != win_by:
            # Allow classic win-by-2 overtime: 12-10, 13-11, ...
            if (winner - loser) < win_by:
                raise ScoreValidationError(f"Must win by {win_by}")

    def submit_score(
        self,
        match_id: int,
        team_a_score: int,
        team_b_score: int,
        *,
        game_to: int = 11,
        win_by: int = 2,
        strict: bool = True,
        rebuild: bool = True,
    ) -> Score:
        match = self.matches.get(match_id)
        if match is None:
            raise ScoreValidationError("Match not found")
        if self.scores.get_for_match(match_id) is not None:
            raise ScoreValidationError("Match already has a score — edit instead")

        self.validate_score(
            team_a_score, team_b_score, game_to=game_to, win_by=win_by, strict=strict
        )
        winner_team_id = (
            match.team_a_id if team_a_score > team_b_score else match.team_b_id
        )
        # Update status before inserting child score row (DuckDB FK update quirk)
        self.matches.set_status(match_id, MatchStatus.COMPLETED)
        score = self.scores.insert(
            match_id, team_a_score, team_b_score, winner_team_id
        )
        self._audit(
            "score",
            score.id,
            "submit",
            None,
            {
                "match_id": match_id,
                "team_a_score": team_a_score,
                "team_b_score": team_b_score,
            },
        )
        if rebuild:
            self.recompute.rebuild_all()
        return score

    def edit_score(
        self,
        match_id: int,
        team_a_score: int,
        team_b_score: int,
        *,
        game_to: int = 11,
        win_by: int = 2,
        strict: bool = True,
        rebuild: bool = True,
    ) -> Score:
        match = self.matches.get(match_id)
        if match is None:
            raise ScoreValidationError("Match not found")
        existing = self.scores.get_for_match(match_id)
        if existing is None:
            raise ScoreValidationError("No score to edit — submit first")

        self.validate_score(
            team_a_score, team_b_score, game_to=game_to, win_by=win_by, strict=strict
        )
        winner_team_id = (
            match.team_a_id if team_a_score > team_b_score else match.team_b_id
        )
        before = {
            "team_a_score": existing.team_a_score,
            "team_b_score": existing.team_b_score,
        }
        score = self.scores.update(
            match_id, team_a_score, team_b_score, winner_team_id
        )
        self.matches.set_status(match_id, MatchStatus.COMPLETED)
        self._audit(
            "score",
            score.id,
            "edit",
            before,
            {"team_a_score": team_a_score, "team_b_score": team_b_score},
        )
        if rebuild:
            self.recompute.rebuild_all()
        return score

    def undo_score(self, match_id: int, *, rebuild: bool = True) -> None:
        existing = self.scores.get_for_match(match_id)
        if existing is None:
            raise ScoreValidationError("No score to undo")
        before = {
            "team_a_score": existing.team_a_score,
            "team_b_score": existing.team_b_score,
        }
        self.scores.delete_for_match(match_id)
        self.conn.execute("DELETE FROM elo_history WHERE match_id = ?", [match_id])
        self.conn.execute("DELETE FROM match_summaries WHERE match_id = ?", [match_id])
        self.matches.set_status(match_id, MatchStatus.SCHEDULED)
        self._audit("score", existing.id, "undo", before, None)
        if rebuild:
            self.recompute.rebuild_all()

    def match_label(self, match: Match) -> dict:
        a1, a2 = self.teams.get_player_ids(match.team_a_id)
        b1, b2 = self.teams.get_player_ids(match.team_b_id)
        names = {
            int(r[0]): r[1]
            for r in self.conn.execute(
                "SELECT id, COALESCE(display_name, name) FROM players"
            ).fetchall()
        }
        return {
            "a1": names.get(a1, str(a1)),
            "a2": names.get(a2, str(a2)),
            "b1": names.get(b1, str(b1)),
            "b2": names.get(b2, str(b2)),
            "court": match.court,
            "round": match.round_number,
            "order": match.match_order,
        }

    def _audit(
        self,
        entity_type: str,
        entity_id: int | None,
        action: str,
        before: dict | None,
        after: dict | None,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO audit_log (entity_type, entity_id, action, before_json, after_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                entity_type,
                entity_id,
                action,
                json.dumps(before) if before is not None else None,
                json.dumps(after) if after is not None else None,
            ],
        )
