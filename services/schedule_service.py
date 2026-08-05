"""Schedule orchestration — manual edits and generator hooks."""

from __future__ import annotations

import json
import math

import duckdb

from database.connection import get_connection
from models.enums import MatchStatus
from models.match import FINALE_ROUND, Match, finale_label_for_bracket
from repositories.events import EventRepository
from repositories.matches import MatchRepository
from repositories.players import PlayerRepository
from repositories.scores import ScoreRepository
from scheduling.base import ProposedMatch, ScheduleRequest, ScheduleResult
from scheduling.social_rotation import SocialRotationGenerator


def _is_missing(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    text = str(value).strip().casefold()
    return text in ("", "nan", "none")


class ScheduleService:
    def __init__(self, conn: duckdb.DuckDBPyConnection | None = None) -> None:
        self.conn = conn or get_connection()
        self.matches = MatchRepository(self.conn)
        self.scores = ScoreRepository(self.conn)
        self.events = EventRepository(self.conn)
        self.players = PlayerRepository(self.conn)
        self.generator = SocialRotationGenerator()

    def list_matches(self, event_id: int) -> list[Match]:
        return self.matches.list_for_event(event_id)

    def schedule_df(self, event_id: int):
        return self.matches.event_schedule_df(event_id)

    def add_match(
        self,
        event_id: int,
        *,
        a1: int,
        a2: int,
        b1: int,
        b2: int,
        round_number: int = 1,
        court: int | None = None,
        match_order: int | None = None,
    ) -> Match:
        self._validate_round_player_uniqueness(
            event_id=event_id,
            round_number=round_number,
            players=(a1, a2, b1, b2),
        )
        match = self.matches.create(
            event_id,
            team_a_players=(a1, a2),
            team_b_players=(b1, b2),
            round_number=round_number,
            court=court,
            match_order=match_order,
        )
        self._audit("match", match.id, "create", None, {"match_id": match.id})
        return match

    def update_scheduled_match(
        self,
        match_id: int,
        *,
        a1: int,
        a2: int,
        b1: int,
        b2: int,
        round_number: int | None = None,
        court: int | None = None,
        match_order: int | None = None,
    ) -> Match:
        match = self.matches.get(match_id)
        if match is None:
            raise ValueError("Match not found")
        if match.status == MatchStatus.COMPLETED:
            raise ValueError("Use unlock/edit flow for completed matches")
        if self.scores.get_for_match(match_id) is not None:
            raise ValueError("Match already has a score")

        before = {
            "team_a_id": match.team_a_id,
            "team_b_id": match.team_b_id,
            "round_number": match.round_number,
            "court": match.court,
            "match_order": match.match_order,
        }
        updated = self.matches.update_lineup(
            match_id,
            team_a_players=(a1, a2),
            team_b_players=(b1, b2),
            round_number=round_number,
            court=court,
            match_order=match_order,
        )
        self._audit(
            "match",
            match_id,
            "update_lineup",
            before,
            {
                "team_a_id": updated.team_a_id,
                "team_b_id": updated.team_b_id,
                "round_number": updated.round_number,
                "court": updated.court,
                "match_order": updated.match_order,
            },
        )
        return updated

    def delete_match(self, match_id: int) -> None:
        match = self.matches.get(match_id)
        if match is None:
            return
        if self.scores.get_for_match(match_id) is not None:
            raise ValueError("Cannot delete a scored match — clear the score first")
        self.matches.delete(match_id)
        self._audit("match", match_id, "delete", {"event_id": match.event_id}, None)

    def clear_scheduled_matches(self, event_id: int) -> int:
        """Delete all unscored scheduled matches for an event. Returns count deleted."""
        deleted = 0
        for match in self.matches.list_for_event(event_id):
            if match.status != MatchStatus.SCHEDULED:
                continue
            if self.scores.get_for_match(match.id) is not None:
                continue
            self.matches.delete(match.id)
            deleted += 1
        return deleted

    def import_schedule(
        self,
        event_id: int,
        rows: list[dict],
        *,
        replace_unscored: bool = True,
        name_to_id: dict[str, int] | None = None,
        create_missing_players: bool = True,
    ) -> dict:
        """
        Import scheduled matches from parsed rows.

        Each row needs: player_a1, player_a2, player_b1, player_b2, round_number,
        and optionally court, match_order, is_finale, finale_label.
        Player fields are names resolved via name_to_id (casefold keys).
        Missing players are created and added as attendees when
        create_missing_players is True.
        """
        event = self.events.get(event_id)
        if event is None:
            raise ValueError("Event not found")
        if not rows:
            raise ValueError("No matches to import")

        lookup = {k.strip().casefold(): v for k, v in (name_to_id or {}).items()}
        for p in self.players.list_players(active_only=False):
            if p.name:
                lookup.setdefault(p.name.strip().casefold(), p.id)
            if p.display_name:
                lookup.setdefault(p.display_name.strip().casefold(), p.id)
            if p.label:
                lookup.setdefault(p.label.strip().casefold(), p.id)

        attendee_ids = set(self.events.get_player_ids(event_id))
        created_players: list[str] = []
        added_attendees: list[str] = []

        def ensure_player(name: object) -> int:
            raw = str(name).strip()
            key = raw.casefold()
            if not key or key == "nan":
                raise ValueError("Blank player name in schedule upload")
            pid = lookup.get(key)
            if pid is not None:
                return int(pid)
            existing = self.players.find_by_name(raw)
            if existing is not None:
                lookup[key] = existing.id
                return existing.id
            if not create_missing_players:
                raise ValueError(f"Unknown player: {raw}")
            created = self.players.create(raw)
            lookup[key] = created.id
            created_players.append(created.name)
            return created.id

        def ensure_attendee(pid: int, label: object) -> None:
            if pid in attendee_ids:
                return
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
            attendee_ids.add(pid)
            added_attendees.append(str(label).strip())

        resolved: list[dict] = []
        for i, row in enumerate(rows, start=1):
            try:
                a1 = ensure_player(row["player_a1"])
                a2 = ensure_player(row["player_a2"])
                b1 = ensure_player(row["player_b1"])
                b2 = ensure_player(row["player_b2"])
            except ValueError as exc:
                raise ValueError(f"Row {i}: {exc}") from exc
            for pid, label in [
                (a1, row["player_a1"]),
                (a2, row["player_a2"]),
                (b1, row["player_b1"]),
                (b2, row["player_b2"]),
            ]:
                ensure_attendee(pid, label)
            round_number = int(row.get("round_number") or 1)
            court = row.get("court")
            court_i = None if _is_missing(court) else int(court)
            match_order = row.get("match_order")
            order_i = None if _is_missing(match_order) else int(match_order)
            finale_label = row.get("finale_label")
            if _is_missing(finale_label):
                finale_label = None
            else:
                finale_label = str(finale_label).strip()
            resolved.append(
                {
                    "a1": a1,
                    "a2": a2,
                    "b1": b1,
                    "b2": b2,
                    "round_number": round_number,
                    "court": court_i,
                    "match_order": order_i,
                    "is_finale": bool(row.get("is_finale", False)),
                    "finale_label": finale_label,
                }
            )

        cleared = 0
        if replace_unscored:
            cleared = self.clear_scheduled_matches(event_id)

        created: list[Match] = []
        for i, item in enumerate(resolved, start=1):
            try:
                self._validate_round_player_uniqueness(
                    event_id=event_id,
                    round_number=item["round_number"],
                    players=(item["a1"], item["a2"], item["b1"], item["b2"]),
                )
                match = self.matches.create(
                    event_id,
                    team_a_players=(item["a1"], item["a2"]),
                    team_b_players=(item["b1"], item["b2"]),
                    round_number=item["round_number"],
                    court=item["court"],
                    match_order=item["match_order"],
                    is_finale=item["is_finale"],
                    finale_label=item["finale_label"],
                )
            except ValueError as exc:
                raise ValueError(f"Row {i}: {exc}") from exc
            created.append(match)

        self._audit(
            "event",
            event_id,
            "import_schedule",
            None,
            {
                "created": len(created),
                "cleared_unscored": cleared,
                "created_players": created_players,
                "added_attendees": added_attendees,
            },
        )
        return {
            "created": len(created),
            "cleared_unscored": cleared,
            "created_players": created_players,
            "added_attendees": added_attendees,
        }

    def generate_schedule(
        self,
        event_id: int,
        *,
        num_rounds: int,
        seed: int = 42,
        replace_existing: bool = True,
        balance_elo: bool = True,
    ) -> ScheduleResult:
        event = self.events.get(event_id)
        if event is None:
            raise ValueError("Event not found")
        player_ids = self.events.get_player_ids(event_id)
        if len(player_ids) < 4:
            raise ValueError("Need at least 4 attendees")

        elo_by_player = None
        if balance_elo:
            elo_by_player = {
                p.id: p.current_elo for p in self.players.list_players() if p.id in set(player_ids)
            }

        completed: list[ProposedMatch] = []
        for match in self.matches.list_for_event(event_id):
            if match.status != MatchStatus.COMPLETED:
                continue
            a = self.matches.teams.get_player_ids(match.team_a_id)
            b = self.matches.teams.get_player_ids(match.team_b_id)
            completed.append(
                ProposedMatch(
                    round_number=match.round_number,
                    court=match.court or 1,
                    team_a=a,
                    team_b=b,
                    match_order=match.match_order,
                )
            )

        request = ScheduleRequest(
            player_ids=player_ids,
            num_courts=event.num_courts,
            num_rounds=num_rounds,
            elo_by_player=elo_by_player,
            completed_matches=completed,
            seed=seed,
        )
        result = self.generator.generate(request)

        if replace_existing:
            self.clear_scheduled_matches(event_id)

        # Continue match_order after existing matches
        existing = self.matches.list_for_event(event_id)
        next_order = max((m.match_order for m in existing), default=0) + 1
        round_offset = max((m.round_number for m in existing), default=0)

        for proposed in result.matches:
            self.matches.create(
                event_id,
                team_a_players=proposed.team_a,
                team_b_players=proposed.team_b,
                round_number=proposed.round_number + round_offset,
                court=proposed.court,
                match_order=next_order,
            )
            next_order += 1

        self._audit(
            "event",
            event_id,
            "generate_schedule",
            None,
            {"rounds": num_rounds, "matches": len(result.matches)},
        )
        return result

    def generate_playoff_round(
        self,
        event_id: int,
        *,
        clear_unplayed: bool = True,
    ) -> dict:
        """
        Create one playoff round seeded by tonight's power rankings:
        1+4 vs 2+3, 5+8 vs 6+7, ...
        """
        from services.analytics_service import AnalyticsService

        event = self.events.get(event_id)
        if event is None:
            raise ValueError("Event not found")

        attendee_ids = self.events.get_player_ids(event_id)
        if len(attendee_ids) < 4:
            raise ValueError("Need at least 4 attendees for playoffs")

        if clear_unplayed:
            self.clear_scheduled_matches(event_id)

        live = AnalyticsService(self.conn).live_event_player_metrics(event_id)
        if live.empty:
            # Fall back to event standings if no completed games yet.
            standings_rows = self.conn.execute(
                """
                SELECT player_id
                FROM event_standings
                WHERE event_id = ?
                ORDER BY wins DESC, point_diff DESC, elo DESC, player_id
                """,
                [event_id],
            ).fetchall()
            seeded_ids = [int(r[0]) for r in standings_rows]
        else:
            ranked = live.sort_values(
                ["power_score", "wins", "point_diff", "elo_delta_tonight"],
                ascending=[False, False, False, False],
            )
            seeded_ids = [int(pid) for pid in ranked["player_id"].tolist()]

        # Include attendees missing from rankings (defensive fallback).
        missing = [pid for pid in attendee_ids if pid not in set(seeded_ids)]
        seeded_ids.extend(sorted(missing))
        seeded_ids = [pid for pid in seeded_ids if pid in set(attendee_ids)]

        if len(seeded_ids) < 4:
            raise ValueError("Not enough seeded players for playoff generation")

        existing = self.matches.list_for_event(event_id)
        # Always park finales on FINALE_ROUND (99) so they stay past any RR length.
        playoff_round = FINALE_ROUND
        next_order = max((m.match_order for m in existing), default=0) + 1

        created_matches: list[Match] = []
        num_courts = max(int(event.num_courts), 1)
        quartets = len(seeded_ids) // 4
        for i in range(quartets):
            group = seeded_ids[i * 4 : (i + 1) * 4]  # [1,2,3,4] seed order
            team_a = (group[0], group[3])  # 1 + 4
            team_b = (group[1], group[2])  # 2 + 3
            court = (i % num_courts) + 1
            finale_label = finale_label_for_bracket(i)
            match = self.matches.create(
                event_id,
                team_a_players=team_a,
                team_b_players=team_b,
                round_number=playoff_round,
                court=court,
                match_order=next_order,
                is_finale=True,
                finale_label=finale_label,
            )
            created_matches.append(match)
            next_order += 1

        seeded_used = quartets * 4
        unseeded_ids = seeded_ids[seeded_used:]
        unseeded_names = []
        for pid in unseeded_ids:
            player = self.players.get(pid)
            unseeded_names.append(player.display_name if player and player.display_name else player.name if player else str(pid))

        self._audit(
            "event",
            event_id,
            "generate_playoff_round",
            None,
            {
                "round_number": playoff_round,
                "is_finale": True,
                "matches_created": len(created_matches),
                "clear_unplayed": clear_unplayed,
                "unseeded_count": len(unseeded_ids),
                "finale_labels": [m.finale_label for m in created_matches],
            },
        )
        return {
            "round_number": playoff_round,
            "matches_created": len(created_matches),
            "unseeded_players": unseeded_names,
            "finale_labels": [m.finale_label for m in created_matches],
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

    def _validate_round_player_uniqueness(
        self,
        *,
        event_id: int,
        round_number: int,
        players: tuple[int, int, int, int],
        exclude_match_id: int | None = None,
    ) -> None:
        """
        Ensure each player appears at most once per round for an event.
        """
        incoming_players = set(players)
        if len(incoming_players) != 4:
            # Let repository-level "four distinct players" validation raise a clearer error.
            return

        for existing in self.matches.list_for_event(event_id):
            if existing.round_number != round_number:
                continue
            if exclude_match_id is not None and existing.id == exclude_match_id:
                continue

            existing_players = set(self.matches.teams.get_player_ids(existing.team_a_id)) | set(
                self.matches.teams.get_player_ids(existing.team_b_id)
            )
            overlapping = incoming_players & existing_players
            if not overlapping:
                continue

            overlap_names = sorted(
                {
                    (
                        player.display_name
                        or player.name
                        or f"Player {player_id}"
                    )
                    for player_id in overlapping
                    for player in [self.players.get(player_id)]
                    if player is not None
                }
            )
            overlap_label = ", ".join(overlap_names) if overlap_names else "selected players"
            raise ValueError(
                f"Round {round_number} already includes {overlap_label}. "
                "Each player can appear only once per round."
            )
