"""Validation helpers for uploaded match CSVs."""

from __future__ import annotations

import pandas as pd

from import_.templates import MATCHES_COLUMNS_REQUIRED


def validate_matches_df(df: pd.DataFrame) -> list[str]:
    errors: list[str] = []
    missing = [c for c in MATCHES_COLUMNS_REQUIRED if c not in df.columns]
    if missing:
        errors.append(f"Missing required columns: {', '.join(missing)}")
        return errors
    if df.empty:
        errors.append("CSV has no rows.")
        return errors

    for col in ["score_a", "score_b"]:
        if not pd.to_numeric(df[col], errors="coerce").notna().all():
            errors.append(f"Column '{col}' must be numeric.")

    required_player_cols = ["player_a1", "player_a2", "player_b1", "player_b2"]
    for col in required_player_cols:
        if (df[col].astype(str).str.strip() == "").any():
            errors.append(f"Column '{col}' contains blank names.")

    return errors
