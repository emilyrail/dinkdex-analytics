"""Greedy social-rotation schedule generator with local search."""

from __future__ import annotations

import itertools
import math
import random

from scheduling.base import CostWeights, ProposedMatch, ScheduleRequest, ScheduleResult
from scheduling.cost import partner_key, score_schedule
from scheduling.pairings import pairings_for_four
from scheduling.sitouts import choose_sitouts, player_units

Team = tuple[int, int]


def fixed_partner_map(fixed_teams: list[Team], player_ids: list[int]) -> dict[int, int]:
    """Validate fixed teams and return a player -> partner lookup."""
    present = set(player_ids)
    partner: dict[int, int] = {}
    for a, b in fixed_teams:
        if a == b:
            raise ValueError("A fixed team needs two different players")
        if a not in present or b not in present:
            raise ValueError("Both fixed partners must be attending")
        for pid in (a, b):
            if pid in partner:
                raise ValueError("A player can only be in one fixed team")
        partner[a] = b
        partner[b] = a
    return partner


def valid_pairings(
    group: list[int], fixed_partner: dict[int, int]
) -> list[tuple[Team, Team]]:
    options = pairings_for_four(*group)
    if not fixed_partner:
        return options
    return [
        (ta, tb)
        for ta, tb in options
        if _respects_fixed(ta, fixed_partner) and _respects_fixed(tb, fixed_partner)
    ]


def _respects_fixed(team: Team, fixed_partner: dict[int, int]) -> bool:
    a, b = team
    return fixed_partner.get(a, b) == b and fixed_partner.get(b, a) == a


class SocialRotationGenerator:
    local_search_iterations = 2000
    start_temperature = 2.0

    def generate(self, request: ScheduleRequest) -> ScheduleResult:
        players = list(request.player_ids)
        if len(players) < 4:
            raise ValueError("Need at least 4 players")
        if request.num_courts < 1:
            raise ValueError("Need at least 1 court")
        fixed_partner = fixed_partner_map(request.fixed_teams, players)

        active_slots = min(len(players), request.num_courts * 4)
        active_slots = active_slots - (active_slots % 4)
        if active_slots < 4:
            raise ValueError("Not enough players/courts for a match")

        num_rounds = request.num_rounds
        if num_rounds is None:
            if request.games_per_player:
                # each round a player plays with probability active_slots/n
                n = len(players)
                games_per_round = active_slots / n
                num_rounds = max(1, int(round(request.games_per_player / games_per_round)))
            else:
                num_rounds = max(4, len(players) - 1)

        rng = random.Random(request.seed)
        best: ScheduleResult | None = None

        # Multi-start greedy
        for attempt in range(8):
            seed = None if request.seed is None else request.seed + attempt
            result = self._greedy(
                request, players, fixed_partner, active_slots, num_rounds, seed
            )
            result = self._local_search(request, result, fixed_partner, rng)
            if best is None or result.quality.total_cost < best.quality.total_cost:
                best = result

        assert best is not None
        return best

    def _greedy(
        self,
        request: ScheduleRequest,
        players: list[int],
        fixed_partner: dict[int, int],
        active_slots: int,
        num_rounds: int,
        seed: int | None,
    ) -> ScheduleResult:
        rng = random.Random(seed)
        partner_counts: dict[Team, int] = {}
        opponent_counts: dict[Team, int] = {}
        games = {p: 0 for p in players}
        sitout_counts = {p: 0 for p in players}
        recent_sitouts: set[int] = set()
        matches: list[ProposedMatch] = []
        sit_outs_by_round: dict[int, list[int]] = {}
        order = 1

        def record(team_a: Team, team_b: Team) -> None:
            for team in (team_a, team_b):
                key = partner_key(*team)
                partner_counts[key] = partner_counts.get(key, 0) + 1
            for x in team_a:
                for y in team_b:
                    key = partner_key(x, y)
                    opponent_counts[key] = opponent_counts.get(key, 0) + 1
            for pid in (*team_a, *team_b):
                games[pid] = games.get(pid, 0) + 1

        # Seed partner/opponent counts from completed matches
        for m in request.completed_matches:
            record(m.team_a, m.team_b)

        for round_number in range(1, num_rounds + 1):
            sits = choose_sitouts(
                players,
                active_slots=active_slots,
                sitout_counts=sitout_counts,
                recent_sitouts=recent_sitouts,
                rng=rng,
                fixed_partner=fixed_partner,
            )
            sit_outs_by_round[round_number] = sits
            for pid in sits:
                sitout_counts[pid] = sitout_counts.get(pid, 0) + 1
            recent_sitouts = set(sits)

            active = [p for p in players if p not in set(sits)]
            rng.shuffle(active)
            courts = active_slots // 4

            if fixed_partner:
                best_groups = self._random_groups(active, fixed_partner, courts, rng)
            else:
                # Prefer balancing games: sort active by games ascending with noise
                active.sort(key=lambda p: (games.get(p, 0), rng.random()))
                best_groups = [active[i * 4 : (i + 1) * 4] for i in range(courts)]

            # Improve grouping with random trials
            best_group_cost = self._groups_cost(
                best_groups, partner_counts, opponent_counts, fixed_partner, request
            )
            for _ in range(80):
                trial = self._random_groups(active, fixed_partner, courts, rng)
                c = self._groups_cost(
                    trial, partner_counts, opponent_counts, fixed_partner, request
                )
                if c < best_group_cost:
                    best_group_cost = c
                    best_groups = trial

            for court_idx, group in enumerate(best_groups, start=1):
                team_a, team_b = min(
                    valid_pairings(group, fixed_partner),
                    key=lambda p: self._pairing_cost(
                        p[0], p[1], partner_counts, opponent_counts, fixed_partner, request
                    ),
                )
                record(team_a, team_b)
                matches.append(
                    ProposedMatch(
                        round_number=round_number,
                        court=court_idx,
                        team_a=team_a,
                        team_b=team_b,
                        match_order=order,
                    )
                )
                order += 1

        _, quality = self._score(request, matches, players, sit_outs_by_round, fixed_partner)
        return ScheduleResult(matches=matches, sit_outs_by_round=sit_outs_by_round, quality=quality)

    @staticmethod
    def _random_groups(
        active: list[int],
        fixed_partner: dict[int, int],
        courts: int,
        rng: random.Random,
    ) -> list[list[int]]:
        """Randomly pack active players into courts, keeping fixed pairs in one group."""
        units = player_units(active, fixed_partner)
        pairs = [u for u in units if len(u) == 2]
        singles = [u[0] for u in units if len(u) == 1]
        rng.shuffle(pairs)
        rng.shuffle(singles)
        # Choose how many courts host two fixed pairs; the rest host at most one.
        n_pairs = len(pairs)
        options = [g2 for g2 in range(n_pairs // 2 + 1) if courts - g2 - (n_pairs - 2 * g2) >= 0]
        double_pair_courts = rng.choice(options)
        single_pair_courts = n_pairs - 2 * double_pair_courts
        groups: list[list[int]] = []
        for _ in range(double_pair_courts):
            groups.append([*pairs.pop(), *pairs.pop()])
        for _ in range(single_pair_courts):
            groups.append([*pairs.pop(), singles.pop(), singles.pop()])
        while singles:
            groups.append([singles.pop() for _ in range(4)])
        rng.shuffle(groups)
        return groups

    def _groups_cost(
        self,
        groups: list[list[int]],
        partner_counts: dict[Team, int],
        opponent_counts: dict[Team, int],
        fixed_partner: dict[int, int],
        request: ScheduleRequest,
    ) -> float:
        return sum(
            min(
                self._pairing_cost(
                    ta, tb, partner_counts, opponent_counts, fixed_partner, request
                )
                for ta, tb in valid_pairings(group, fixed_partner)
            )
            for group in groups
        )

    @staticmethod
    def _pairing_cost(
        team_a: Team,
        team_b: Team,
        partner_counts: dict[Team, int],
        opponent_counts: dict[Team, int],
        fixed_partner: dict[int, int],
        request: ScheduleRequest,
    ) -> float:
        weights: CostWeights = request.weights
        cost = 0.0
        for team in (team_a, team_b):
            if fixed_partner.get(team[0]) != team[1]:
                cost += weights.partner_repeat * partner_counts.get(team, 0)
        cost += weights.opponent_repeat * sum(
            opponent_counts.get(partner_key(x, y), 0) for x in team_a for y in team_b
        )
        if request.elo_by_player:
            elos = request.elo_by_player
            ra = (elos.get(team_a[0], 1000) + elos.get(team_a[1], 1000)) / 2
            rb = (elos.get(team_b[0], 1000) + elos.get(team_b[1], 1000)) / 2
            cost += weights.partner_repeat * abs(ra - rb) / 100.0
        return cost

    @staticmethod
    def _score(
        request: ScheduleRequest,
        matches: list[ProposedMatch],
        players: list[int],
        sit_outs: dict[int, list[int]],
        fixed_partner: dict[int, int],
    ):
        return score_schedule(
            matches,
            players,
            sit_outs,
            weights=request.weights,
            elo_by_player=request.elo_by_player,
            partner_history_counts=request.partner_history_counts,
            fixed_teams={partner_key(a, b) for a, b in fixed_partner.items()},
        )

    def _local_search(
        self,
        request: ScheduleRequest,
        result: ScheduleResult,
        fixed_partner: dict[int, int],
        rng: random.Random,
    ) -> ScheduleResult:
        """Simulated annealing over pairing flips and same-round player swaps."""
        matches = list(result.matches)
        sit_outs = dict(result.sit_outs_by_round)
        players = list(request.player_ids)
        current_cost, current_quality = self._score(
            request, matches, players, sit_outs, fixed_partner
        )
        best_matches, best_cost, best_quality = matches, current_cost, current_quality

        indices_by_round: dict[int, list[int]] = {}
        for idx, m in enumerate(matches):
            indices_by_round.setdefault(m.round_number, []).append(idx)

        steps = self.local_search_iterations
        for step in range(steps):
            if not matches:
                break
            temperature = self.start_temperature * (1 - step / steps) + 0.01
            i = rng.randrange(len(matches))
            mi = matches[i]
            same_round = [k for k in indices_by_round[mi.round_number] if k != i]
            gi = [mi.team_a[0], mi.team_a[1], mi.team_b[0], mi.team_b[1]]
            candidate = list(matches)

            if same_round and rng.random() < 0.7:
                # Swap a player (or a fixed pair) with players from another court this round
                j = rng.choice(same_round)
                mj = matches[j]
                gj = [mj.team_a[0], mj.team_a[1], mj.team_b[0], mj.team_b[1]]
                unit_a = self._unit_of(rng.choice(gi), fixed_partner)
                unit_b = self._matching_unit(gj, len(unit_a), fixed_partner, rng)
                if unit_b is None:
                    continue
                gi = [x for x in gi if x not in unit_a] + list(unit_b)
                gj = [x for x in gj if x not in unit_b] + list(unit_a)
                ta, tb = rng.choice(valid_pairings(gi, fixed_partner))
                tc, td = rng.choice(valid_pairings(gj, fixed_partner))
                candidate[i] = ProposedMatch(mi.round_number, mi.court, ta, tb, mi.match_order)
                candidate[j] = ProposedMatch(mj.round_number, mj.court, tc, td, mj.match_order)
            else:
                # Flip the pairing inside match i
                options = [
                    p for p in valid_pairings(gi, fixed_partner) if p != (mi.team_a, mi.team_b)
                ]
                if not options:
                    continue
                ta, tb = rng.choice(options)
                candidate[i] = ProposedMatch(mi.round_number, mi.court, ta, tb, mi.match_order)

            cost, quality = self._score(request, candidate, players, sit_outs, fixed_partner)
            if cost <= current_cost or rng.random() < math.exp(
                (current_cost - cost) / temperature
            ):
                matches, current_cost = candidate, cost
                if cost < best_cost:
                    best_matches, best_cost, best_quality = candidate, cost, quality

        return ScheduleResult(
            matches=best_matches,
            sit_outs_by_round=sit_outs,
            quality=best_quality,
        )

    @staticmethod
    def _unit_of(pid: int, fixed_partner: dict[int, int]) -> tuple[int, ...]:
        partner = fixed_partner.get(pid)
        return (pid,) if partner is None else (pid, partner)

    @staticmethod
    def _matching_unit(
        group: list[int],
        size: int,
        fixed_partner: dict[int, int],
        rng: random.Random,
    ) -> tuple[int, ...] | None:
        """Pick players from ``group`` that can trade places with a unit of ``size``."""
        singles = [x for x in group if x not in fixed_partner]
        if size == 1:
            return (rng.choice(singles),) if singles else None
        options: list[tuple[int, ...]] = [
            (x, fixed_partner[x]) for x in group if fixed_partner.get(x, -1) > x
        ]
        options.extend(itertools.combinations(singles, 2))
        return rng.choice(options) if options else None
