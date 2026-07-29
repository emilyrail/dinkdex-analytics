"""Display helpers."""

from __future__ import annotations


def format_elo(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:.0f}"


def format_win_pct(wins: int, losses: int) -> str:
    total = wins + losses
    if total == 0:
        return "—"
    return f"{100.0 * wins / total:.0f}%"


def format_score(a: int, b: int) -> str:
    return f"{a}–{b}"


def streak_label(streak: int) -> str:
    if streak > 0:
        return f"W{streak}"
    if streak < 0:
        return f"L{abs(streak)}"
    return "—"


def provisional_badge_markdown() -> str:
    """Streamlit markdown badge for provisional Elo players."""
    from analytics.elo import PROVISIONAL_BADGE

    return f":orange-badge[{PROVISIONAL_BADGE}]"
