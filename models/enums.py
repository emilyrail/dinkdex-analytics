from __future__ import annotations

from enum import StrEnum


class EventStatus(StrEnum):
    DRAFT = "draft"
    SCHEDULED = "scheduled"
    LIVE = "live"
    COMPLETED = "completed"


class MatchStatus(StrEnum):
    SCHEDULED = "scheduled"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    SKIPPED = "skipped"
