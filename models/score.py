from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Score:
    id: int
    match_id: int
    team_a_score: int
    team_b_score: int
    winner_team_id: int
    submitted_at: datetime | None = None
    updated_at: datetime | None = None
