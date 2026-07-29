"""CSV templates for historical import."""

from __future__ import annotations

MATCHES_COLUMNS_REQUIRED = [
    "event_date",
    "player_a1",
    "player_a2",
    "player_b1",
    "player_b2",
    "score_a",
    "score_b",
]

MATCHES_COLUMNS_OPTIONAL = [
    "event_name",
    "round_number",
    "match_order",
    "court",
]


def sample_csv() -> str:
    return (
        "event_date,event_name,round_number,match_order,court,player_a1,player_a2,"
        "player_b1,player_b2,score_a,score_b\n"
        "2026-07-21,Tuesday Night,1,1,1,Alex,Jordan,Sam,Taylor,11,7\n"
    )
