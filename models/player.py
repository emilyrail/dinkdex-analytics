from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Player:
    id: int
    name: str
    display_name: str | None
    active: bool
    current_elo: float
    created_at: datetime | None = None

    @property
    def label(self) -> str:
        return self.display_name or self.name
