"""Schedule quality report helpers."""

from __future__ import annotations

from scheduling.base import ScheduleQuality, ScheduleResult


def quality_summary(result: ScheduleResult) -> dict:
    q = result.quality
    games = list(q.games_per_player.values())
    return {
        "matches": len(result.matches),
        "rounds": len(result.sit_outs_by_round),
        "partner_repeats": q.partner_repeat_total,
        "opponent_repeats": q.opponent_repeat_total,
        "max_elo_gap": q.max_elo_gap,
        "games_min": min(games) if games else 0,
        "games_max": max(games) if games else 0,
        "total_cost": q.total_cost,
    }
