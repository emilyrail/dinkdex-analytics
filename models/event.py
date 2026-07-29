from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from models.enums import EventStatus


@dataclass(frozen=True)
class Event:
    id: int
    name: str
    event_date: date
    status: EventStatus
    game_to: int
    win_by: int
    num_courts: int
    created_at: datetime | None = None
