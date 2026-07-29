"""Fair sit-out selection."""

from __future__ import annotations

import random


def choose_sitouts(
    player_ids: list[int],
    *,
    active_slots: int,
    sitout_counts: dict[int, int],
    recent_sitouts: set[int],
    rng: random.Random,
) -> list[int]:
    """Pick who sits this round. Prefer low sitout counts and avoid consecutive sits."""
    n_sit = len(player_ids) - active_slots
    if n_sit <= 0:
        return []
    if n_sit >= len(player_ids):
        return list(player_ids)

    def key(pid: int) -> tuple:
        return (
            sitout_counts.get(pid, 0),
            1 if pid in recent_sitouts else 0,
            rng.random(),
        )

    ordered = sorted(player_ids, key=key)
    return ordered[:n_sit]
