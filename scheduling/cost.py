"""Schedule cost / quality helpers."""

from __future__ import annotations

from collections import defaultdict

from scheduling.base import CostWeights, ProposedMatch, ScheduleQuality


def partner_key(a: int, b: int) -> tuple[int, int]:
    return (min(a, b), max(a, b))


def foursome_key(a: tuple[int, int], b: tuple[int, int]) -> frozenset[int]:
    return frozenset([a[0], a[1], b[0], b[1]])


def score_schedule(
    matches: list[ProposedMatch],
    player_ids: list[int],
    sit_outs_by_round: dict[int, list[int]],
    *,
    weights: CostWeights,
    elo_by_player: dict[int, float] | None = None,
    partner_history_counts: dict[tuple[int, int], int] | None = None,
) -> tuple[float, ScheduleQuality]:
    partner_counts: dict[tuple[int, int], int] = defaultdict(int)
    opponent_counts: dict[tuple[int, int], int] = defaultdict(int)
    foursome_counts: dict[frozenset[int], int] = defaultdict(int)
    games = {pid: 0 for pid in player_ids}
    sitouts = {pid: 0 for pid in player_ids}
    max_elo_gap = 0.0
    hist = partner_history_counts or {}
    elos = elo_by_player or {}

    cost = 0.0

    for m in matches:
        for pid in (*m.team_a, *m.team_b):
            games[pid] = games.get(pid, 0) + 1

        pk = partner_key(*m.team_a)
        partner_counts[pk] += 1
        pk2 = partner_key(*m.team_b)
        partner_counts[pk2] += 1

        for pa in m.team_a:
            for pb in m.team_b:
                opponent_counts[partner_key(pa, pb)] += 1

        fk = foursome_key(m.team_a, m.team_b)
        foursome_counts[fk] += 1

        if elos:
            ra = (elos.get(m.team_a[0], 1000) + elos.get(m.team_a[1], 1000)) / 2
            rb = (elos.get(m.team_b[0], 1000) + elos.get(m.team_b[1], 1000)) / 2
            gap = abs(ra - rb)
            max_elo_gap = max(max_elo_gap, gap)
            cost += weights.elo_gap * gap / 50.0

        cost += weights.historical_partner * (
            hist.get(pk, 0) + hist.get(pk2, 0)
        )

    partner_repeat_total = sum(max(0, c - 1) for c in partner_counts.values())
    opponent_repeat_total = sum(max(0, c - 1) for c in opponent_counts.values())
    foursome_repeat = sum(max(0, c - 1) for c in foursome_counts.values())

    cost += weights.partner_repeat * partner_repeat_total
    cost += weights.opponent_repeat * opponent_repeat_total
    cost += weights.foursome_repeat * foursome_repeat

    if games:
        avg = sum(games.values()) / len(games)
        cost += weights.games_imbalance * sum((g - avg) ** 2 for g in games.values())

    for sits in sit_outs_by_round.values():
        for pid in sits:
            sitouts[pid] = sitouts.get(pid, 0) + 1

    # consecutive sit-out penalty approximated by total sitout variance
    if sitouts:
        avg_s = sum(sitouts.values()) / len(sitouts)
        cost += weights.sitout_streak * sum((s - avg_s) ** 2 for s in sitouts.values())

    quality = ScheduleQuality(
        games_per_player=games,
        sitouts_per_player=sitouts,
        partner_repeat_total=partner_repeat_total,
        opponent_repeat_total=opponent_repeat_total,
        max_elo_gap=max_elo_gap,
        total_cost=cost,
    )
    return cost, quality
