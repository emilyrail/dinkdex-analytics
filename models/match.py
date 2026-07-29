from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from models.enums import MatchStatus

# Dedicated high round so finales never collide with long round-robins.
FINALE_ROUND = 99


def finale_label_for_bracket(index: int) -> str:
    """Label for the i-th finale bracket (0-based): Top Seed, then 2, 3, …"""
    if int(index) <= 0:
        return "Top Seed"
    return str(int(index) + 1)


@dataclass(frozen=True)
class Match:
    id: int
    event_id: int
    round_number: int
    match_order: int
    court: int | None
    team_a_id: int
    team_b_id: int
    status: MatchStatus
    import_batch_id: int | None = None
    scheduled_at: datetime | None = None
    is_finale: bool = False
    finale_label: str | None = None

    @property
    def finale_display(self) -> str | None:
        if not self.is_finale:
            return None
        label = (self.finale_label or "").strip()
        return f"Finale - {label}" if label else "Finale"
