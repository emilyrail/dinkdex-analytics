"""Event standings computation from completed matches."""

from __future__ import annotations

from collections import defaultdict

import pandas as pd


def compute_event_standings(matches_df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute per-player standings for one event.

    Expected columns:
      player_id, won (bool), points_for, points_against, match_order, elo (optional end elo)
    One row per player per completed match.
    """
    if matches_df.empty:
        return pd.DataFrame(
            columns=[
                "player_id",
                "wins",
                "losses",
                "points_for",
                "points_against",
                "point_diff",
                "win_pct",
                "current_streak",
            ]
        )

    stats: dict[int, dict] = defaultdict(
        lambda: {
            "wins": 0,
            "losses": 0,
            "points_for": 0,
            "points_against": 0,
            "results": [],
        }
    )

    ordered = matches_df.sort_values(["match_order", "player_id"])
    for _, row in ordered.iterrows():
        pid = int(row["player_id"])
        won = bool(row["won"])
        stats[pid]["wins"] += int(won)
        stats[pid]["losses"] += int(not won)
        stats[pid]["points_for"] += int(row["points_for"])
        stats[pid]["points_against"] += int(row["points_against"])
        stats[pid]["results"].append(won)

    rows = []
    for pid, s in stats.items():
        total = s["wins"] + s["losses"]
        win_pct = (s["wins"] / total) if total else 0.0
        streak = 0
        for won in reversed(s["results"]):
            if won and streak >= 0:
                streak = streak + 1 if streak > 0 else 1
            elif not won and streak <= 0:
                streak = streak - 1 if streak < 0 else -1
            else:
                break
        rows.append(
            {
                "player_id": pid,
                "wins": s["wins"],
                "losses": s["losses"],
                "points_for": s["points_for"],
                "points_against": s["points_against"],
                "point_diff": s["points_for"] - s["points_against"],
                "win_pct": win_pct,
                "current_streak": streak,
            }
        )
    return pd.DataFrame(rows)
