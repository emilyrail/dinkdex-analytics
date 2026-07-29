"""Doubles Elo helpers."""

from __future__ import annotations

from utils.config import (
    ELO_K,
    INITIAL_ELO,
    PROVISIONAL_GAMES,
    PROVISIONAL_K_MULTIPLIER,
)

PROVISIONAL_BADGE = "Provisional"
PROVISIONAL_DEFINITION = "Provisional (fewer than 10 games)"


def expected_score(rating_a: float, rating_b: float) -> float:
    """Probability that side A beats side B."""
    return 1.0 / (1.0 + 10 ** ((rating_b - rating_a) / 400.0))


def team_rating(elo_a: float, elo_b: float) -> float:
    return (elo_a + elo_b) / 2.0


def is_provisional(games_played: int, *, threshold: int = PROVISIONAL_GAMES) -> bool:
    """True while a player has completed fewer than `threshold` games."""
    return int(games_played) < int(threshold)


def k_for_games(
    games_played: int,
    *,
    base_k: float = ELO_K,
    threshold: int = PROVISIONAL_GAMES,
    multiplier: float = PROVISIONAL_K_MULTIPLIER,
) -> float:
    """Return the K-factor for a player entering a match with `games_played` completed."""
    if is_provisional(games_played, threshold=threshold):
        return float(base_k) * float(multiplier)
    return float(base_k)


def elo_deltas(
    winner_elos: tuple[float, float],
    loser_elos: tuple[float, float],
    *,
    k: float = ELO_K,
    winner_ks: tuple[float, float] | None = None,
    loser_ks: tuple[float, float] | None = None,
) -> tuple[tuple[float, float], tuple[float, float]]:
    """Return (winner_deltas, loser_deltas) for the four players.

    When per-player K values are supplied, each player moves by their own K.
    Otherwise the shared `k` is used for everyone (legacy behavior).
    """
    w_team = team_rating(*winner_elos)
    l_team = team_rating(*loser_elos)
    exp_w = expected_score(w_team, l_team)
    result_gap = 1.0 - exp_w

    wk = winner_ks if winner_ks is not None else (k, k)
    lk = loser_ks if loser_ks is not None else (k, k)

    # Split the team result equally across partners, scaled by each player's K.
    w_deltas = (wk[0] * result_gap / 2.0, wk[1] * result_gap / 2.0)
    l_deltas = (lk[0] * (0.0 - result_gap) / 2.0, lk[1] * (0.0 - result_gap) / 2.0)
    return w_deltas, l_deltas


def apply_delta(elo: float, delta: float) -> float:
    return elo + delta


def default_elo() -> float:
    return INITIAL_ELO
