"""Greedy social-rotation schedule generator with local search."""

from __future__ import annotations

import random

from scheduling.base import ProposedMatch, ScheduleRequest, ScheduleResult
from scheduling.cost import partner_key, score_schedule
from scheduling.pairings import pairings_for_four
from scheduling.sitouts import choose_sitouts


class SocialRotationGenerator:
    def generate(self, request: ScheduleRequest) -> ScheduleResult:
        players = list(request.player_ids)
        if len(players) < 4:
            raise ValueError("Need at least 4 players")
        if request.num_courts < 1:
            raise ValueError("Need at least 1 court")

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
            result = self._greedy(request, players, active_slots, num_rounds, seed)
            result = self._local_search(request, result, rng)
            if best is None or result.quality.total_cost < best.quality.total_cost:
                best = result

        assert best is not None
        return best

    def _greedy(
        self,
        request: ScheduleRequest,
        players: list[int],
        active_slots: int,
        num_rounds: int,
        seed: int | None,
    ) -> ScheduleResult:
        rng = random.Random(seed)
        partner_counts: dict[tuple[int, int], int] = {}
        games = {p: 0 for p in players}
        sitout_counts = {p: 0 for p in players}
        recent_sitouts: set[int] = set()
        matches: list[ProposedMatch] = []
        sit_outs_by_round: dict[int, list[int]] = {}
        order = 1

        # Seed partner counts from completed matches
        for m in request.completed_matches:
            partner_counts[partner_key(*m.team_a)] = (
                partner_counts.get(partner_key(*m.team_a), 0) + 1
            )
            partner_counts[partner_key(*m.team_b)] = (
                partner_counts.get(partner_key(*m.team_b), 0) + 1
            )
            for pid in (*m.team_a, *m.team_b):
                games[pid] = games.get(pid, 0) + 1

        for round_number in range(1, num_rounds + 1):
            sits = choose_sitouts(
                players,
                active_slots=active_slots,
                sitout_counts=sitout_counts,
                recent_sitouts=recent_sitouts,
                rng=rng,
            )
            sit_outs_by_round[round_number] = sits
            for pid in sits:
                sitout_counts[pid] = sitout_counts.get(pid, 0) + 1
            recent_sitouts = set(sits)

            active = [p for p in players if p not in set(sits)]
            rng.shuffle(active)

            # Prefer balancing games: sort active by games ascending with noise
            active.sort(key=lambda p: (games.get(p, 0), rng.random()))

            courts = active_slots // 4
            groups: list[list[int]] = []
            remaining = list(active)
            for _ in range(courts):
                group = remaining[:4]
                remaining = remaining[4:]
                # Try a few swaps within leftover to reduce partner repeats
                groups.append(group)

            # Improve grouping with a few random trials among permutations of active
            best_groups = groups
            best_group_cost = self._groups_partner_cost(best_groups, partner_counts)
            for _ in range(40):
                shuffled = list(active)
                rng.shuffle(shuffled)
                trial = [shuffled[i * 4 : (i + 1) * 4] for i in range(courts)]
                c = self._groups_partner_cost(trial, partner_counts)
                if c < best_group_cost:
                    best_group_cost = c
                    best_groups = trial

            for court_idx, group in enumerate(best_groups, start=1):
                best_pairing = None
                best_cost = float("inf")
                for team_a, team_b in pairings_for_four(*group):
                    c = (
                        partner_counts.get(team_a, 0)
                        + partner_counts.get(team_b, 0)
                    )
                    # Elo gap if available
                    if request.elo_by_player:
                        elos = request.elo_by_player
                        ra = (elos.get(team_a[0], 1000) + elos.get(team_a[1], 1000)) / 2
                        rb = (elos.get(team_b[0], 1000) + elos.get(team_b[1], 1000)) / 2
                        c += abs(ra - rb) / 100.0
                    if c < best_cost:
                        best_cost = c
                        best_pairing = (team_a, team_b)
                assert best_pairing is not None
                team_a, team_b = best_pairing
                partner_counts[team_a] = partner_counts.get(team_a, 0) + 1
                partner_counts[team_b] = partner_counts.get(team_b, 0) + 1
                for pid in (*team_a, *team_b):
                    games[pid] = games.get(pid, 0) + 1
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

        _, quality = score_schedule(
            matches,
            players,
            sit_outs_by_round,
            weights=request.weights,
            elo_by_player=request.elo_by_player,
            partner_history_counts=request.partner_history_counts,
        )
        return ScheduleResult(matches=matches, sit_outs_by_round=sit_outs_by_round, quality=quality)

    def _groups_partner_cost(
        self,
        groups: list[list[int]],
        partner_counts: dict[tuple[int, int], int],
    ) -> float:
        cost = 0.0
        for group in groups:
            best = min(
                partner_counts.get(ta, 0) + partner_counts.get(tb, 0)
                for ta, tb in pairings_for_four(*group)
            )
            cost += best
        return cost

    def _local_search(
        self,
        request: ScheduleRequest,
        result: ScheduleResult,
        rng: random.Random,
    ) -> ScheduleResult:
        matches = list(result.matches)
        sit_outs = dict(result.sit_outs_by_round)
        players = list(request.player_ids)
        best_cost, best_quality = score_schedule(
            matches,
            players,
            sit_outs,
            weights=request.weights,
            elo_by_player=request.elo_by_player,
            partner_history_counts=request.partner_history_counts,
        )

        for _ in range(120):
            if len(matches) < 2:
                break
            i, j = rng.sample(range(len(matches)), 2)
            # Try flipping pairing inside match i
            m = matches[i]
            group = [m.team_a[0], m.team_a[1], m.team_b[0], m.team_b[1]]
            options = pairings_for_four(*group)
            ta, tb = rng.choice(options)
            candidate = list(matches)
            candidate[i] = ProposedMatch(
                round_number=m.round_number,
                court=m.court,
                team_a=ta,
                team_b=tb,
                match_order=m.match_order,
            )
            cost, quality = score_schedule(
                candidate,
                players,
                sit_outs,
                weights=request.weights,
                elo_by_player=request.elo_by_player,
                partner_history_counts=request.partner_history_counts,
            )
            if cost < best_cost:
                matches = candidate
                best_cost = cost
                best_quality = quality

            # Occasionally swap one player between two matches in same round
            mi, mj = matches[i], matches[j]
            if mi.round_number != mj.round_number:
                continue
            gi = [mi.team_a[0], mi.team_a[1], mi.team_b[0], mi.team_b[1]]
            gj = [mj.team_a[0], mj.team_a[1], mj.team_b[0], mj.team_b[1]]
            a = rng.choice(gi)
            b = rng.choice(gj)
            gi = [b if x == a else x for x in gi]
            gj = [a if x == b else x for x in gj]
            if len(set(gi)) != 4 or len(set(gj)) != 4:
                continue
            ta, tb = rng.choice(pairings_for_four(*gi))
            tc, td = rng.choice(pairings_for_four(*gj))
            candidate = list(matches)
            candidate[i] = ProposedMatch(mi.round_number, mi.court, ta, tb, mi.match_order)
            candidate[j] = ProposedMatch(mj.round_number, mj.court, tc, td, mj.match_order)
            cost, quality = score_schedule(
                candidate,
                players,
                sit_outs,
                weights=request.weights,
                elo_by_player=request.elo_by_player,
                partner_history_counts=request.partner_history_counts,
            )
            if cost < best_cost:
                matches = candidate
                best_cost = cost
                best_quality = quality

        return ScheduleResult(
            matches=matches,
            sit_outs_by_round=sit_outs,
            quality=best_quality,
        )
