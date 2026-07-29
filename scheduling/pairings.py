"""Pairing enumeration for four players."""

from __future__ import annotations


def pairings_for_four(a: int, b: int, c: int, d: int) -> list[tuple[tuple[int, int], tuple[int, int]]]:
    """Return the three distinct doubles pairings for players a,b,c,d."""
    players = [a, b, c, d]
    return [
        (_norm(players[0], players[1]), _norm(players[2], players[3])),
        (_norm(players[0], players[2]), _norm(players[1], players[3])),
        (_norm(players[0], players[3]), _norm(players[1], players[2])),
    ]


def _norm(x: int, y: int) -> tuple[int, int]:
    return (min(x, y), max(x, y))
