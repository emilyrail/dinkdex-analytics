"""Scheduling types and protocols."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class ProposedMatch:
    round_number: int
    court: int
    team_a: tuple[int, int]
    team_b: tuple[int, int]
    match_order: int = 0


@dataclass
class CostWeights:
    partner_repeat: float = 5.0
    opponent_repeat: float = 2.0
    games_imbalance: float = 4.0
    sitout_streak: float = 3.0
    elo_gap: float = 1.5
    historical_partner: float = 1.0
    foursome_repeat: float = 2.5


@dataclass
class ScheduleRequest:
    player_ids: list[int]
    num_courts: int
    num_rounds: int | None = None
    games_per_player: int | None = None
    elo_by_player: dict[int, float] | None = None
    partner_history_counts: dict[tuple[int, int], int] | None = None
    locked_matches: list[ProposedMatch] = field(default_factory=list)
    completed_matches: list[ProposedMatch] = field(default_factory=list)
    weights: CostWeights = field(default_factory=CostWeights)
    seed: int | None = 42


@dataclass
class ScheduleQuality:
    games_per_player: dict[int, int]
    sitouts_per_player: dict[int, int]
    partner_repeat_total: int
    opponent_repeat_total: int
    max_elo_gap: float
    total_cost: float


@dataclass
class ScheduleResult:
    matches: list[ProposedMatch]
    sit_outs_by_round: dict[int, list[int]]
    quality: ScheduleQuality


class ScheduleGenerator(Protocol):
    def generate(self, request: ScheduleRequest) -> ScheduleResult: ...
