"""Mid-event reshuffle helpers."""

from __future__ import annotations

from scheduling.base import ProposedMatch, ScheduleRequest, ScheduleResult
from scheduling.social_rotation import SocialRotationGenerator


def reshuffle_remaining(
    request: ScheduleRequest,
    *,
    remaining_rounds: int,
) -> ScheduleResult:
    """Generate only upcoming rounds, seeding partner/game counts from completed."""
    req = ScheduleRequest(
        player_ids=request.player_ids,
        num_courts=request.num_courts,
        num_rounds=remaining_rounds,
        elo_by_player=request.elo_by_player,
        partner_history_counts=request.partner_history_counts,
        completed_matches=request.completed_matches,
        weights=request.weights,
        seed=request.seed,
    )
    result = SocialRotationGenerator().generate(req)
    # Offset match_order / round numbers if needed by caller
    return result
