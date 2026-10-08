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
    fixed_partner: dict[int, int] | None = None,
) -> list[int]:
    """Pick who sits this round. Prefer low sitout counts and avoid consecutive sits.

    Players in ``fixed_partner`` always sit out together with their partner.
    """
    n_sit = len(player_ids) - active_slots
    if n_sit <= 0:
        return []
    if n_sit >= len(player_ids):
        return list(player_ids)

    if not fixed_partner:

        def key(pid: int) -> tuple:
            return (
                sitout_counts.get(pid, 0),
                1 if pid in recent_sitouts else 0,
                rng.random(),
            )

        ordered = sorted(player_ids, key=key)
        return ordered[:n_sit]

    units = player_units(player_ids, fixed_partner)

    def unit_key(unit: tuple[int, ...]) -> tuple:
        return (
            max(sitout_counts.get(pid, 0) for pid in unit),
            1 if any(pid in recent_sitouts for pid in unit) else 0,
            rng.random(),
        )

    ordered_units = sorted(units, key=unit_key)
    pairs_left = sum(1 for u in ordered_units if len(u) == 2)
    singles_left = len(ordered_units) - pairs_left
    chosen: list[int] = []
    remaining = n_sit
    for unit in ordered_units:
        if remaining == 0:
            break
        if len(unit) == 2:
            pairs_left -= 1
        else:
            singles_left -= 1
        after = remaining - len(unit)
        if after >= 0 and _fillable(after, pairs_left, singles_left):
            chosen.extend(unit)
            remaining = after
    if remaining != 0:
        raise ValueError("Could not choose sit-outs that keep fixed partners together")
    return chosen


def player_units(
    player_ids: list[int], fixed_partner: dict[int, int]
) -> list[tuple[int, ...]]:
    """Group players into fixed pairs and singles."""
    seen: set[int] = set()
    units: list[tuple[int, ...]] = []
    for pid in player_ids:
        if pid in seen:
            continue
        partner = fixed_partner.get(pid)
        if partner is not None:
            units.append((pid, partner))
            seen.update((pid, partner))
        else:
            units.append((pid,))
            seen.add(pid)
    return units


def _fillable(slots: int, pairs: int, singles: int) -> bool:
    return any(0 <= slots - 2 * k <= singles for k in range(min(pairs, slots // 2) + 1))
