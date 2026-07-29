"""Parsers for historical CSV imports."""

from __future__ import annotations

import re

import pandas as pd

from models.match import FINALE_ROUND

_FINALE_ROUND_MAP = {
    "finale - top seed": "Top Seed",
    "finale-top seed": "Top Seed",
    "top seed": "Top Seed",
    "finale - 2": "2",
    "finale-2": "2",
    "finale - 3": "3",
    "finale-3": "3",
    "finale - consolation": "Consolation",
    "finale-consolation": "Consolation",
    "consolation": "Consolation",
    "finale - runner-up": "Runner-up",
    "finale - runner up": "Runner-up",
    "finale-runner-up": "Runner-up",
    "runner-up": "Runner-up",
    "runner up": "Runner-up",
}


def normalize_matches_df(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for c in ["player_a1", "player_a2", "player_b1", "player_b2", "event_name"]:
        if c in out.columns:
            out[c] = out[c].astype(str).str.strip()

    out["event_date"] = pd.to_datetime(out["event_date"]).dt.date
    out["score_a"] = out["score_a"].astype(int)
    out["score_b"] = out["score_b"].astype(int)

    if "round_number" not in out.columns:
        out["round_number"] = 1
    if "match_order" not in out.columns:
        out["match_order"] = list(range(1, len(out) + 1))
    if "court" in out.columns:
        out["court"] = out["court"].apply(_parse_court)
    else:
        out["court"] = None

    parsed = out["round_number"].map(_parse_round)
    out["round_number"] = [r for r, _ in parsed]
    out["is_finale"] = [label is not None for _, label in parsed]
    out["finale_label"] = [label for _, label in parsed]

    out = out.sort_values(["event_date", "match_order"]).reset_index(drop=True)
    return out


def normalize_schedule_upload_df(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize a schedule CSV (upcoming matches). Scores are ignored if present."""
    out = df.copy()
    out.columns = [str(c).strip().lower() for c in out.columns]
    rename = {}
    if "round" in out.columns and "round_number" not in out.columns:
        rename["round"] = "round_number"
    out = out.rename(columns=rename)

    required = ["player_a1", "player_a2", "player_b1", "player_b2"]
    missing = [c for c in required if c not in out.columns]
    if missing:
        raise ValueError(f"Schedule CSV missing columns: {', '.join(missing)}")
    if "round_number" not in out.columns:
        out["round_number"] = 1

    for c in required:
        out[c] = out[c].astype(str).str.strip()

    parsed = out["round_number"].map(_parse_round)
    out["round_number"] = [r for r, _ in parsed]
    out["is_finale"] = [label is not None for _, label in parsed]
    out["finale_label"] = [label for _, label in parsed]

    if "court" in out.columns:
        out["court"] = out["court"].apply(_parse_court)
    else:
        out["court"] = None

    if "match_order" in out.columns:
        out["match_order"] = pd.to_numeric(out["match_order"], errors="coerce")
    else:
        out["match_order"] = list(range(1, len(out) + 1))

    out = out.sort_values(["round_number", "match_order"], kind="stable").reset_index(drop=True)
    return out


def _parse_round(value: object) -> tuple[int, str | None]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return 1, None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return int(value), None
    s = str(value).strip()
    if not s:
        return 1, None
    key = re.sub(r"\s+", " ", s.lower())
    if key in _FINALE_ROUND_MAP:
        return FINALE_ROUND, _FINALE_ROUND_MAP[key]
    if key.startswith("finale"):
        # Unknown finale subtype — still mark as finale on the shared round.
        raw = s.split("-", 1)[-1].strip() if "-" in s else ""
        if raw.isdigit():
            return FINALE_ROUND, raw
        if raw:
            return FINALE_ROUND, raw.title()
        return FINALE_ROUND, None
    m = re.search(r"(\d+)", s)
    return (int(m.group(1)), None) if m else (1, None)


def _parse_court(value: object) -> int | None:
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    m = re.search(r"(\d+)", s)
    return int(m.group(1)) if m else None
