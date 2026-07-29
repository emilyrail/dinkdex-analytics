"""Event orchestration."""

from __future__ import annotations

from datetime import date

from models.enums import EventStatus
from models.event import Event
from repositories.events import EventRepository
from repositories.players import PlayerRepository
from utils.config import DEFAULT_GAME_TO, DEFAULT_NUM_COURTS, DEFAULT_WIN_BY


class EventService:
    def __init__(
        self,
        events: EventRepository | None = None,
        players: PlayerRepository | None = None,
    ) -> None:
        self.events = events or EventRepository()
        self.players = players or PlayerRepository()

    def list_events(self) -> list[Event]:
        return self.events.list_events()

    def get_event(self, event_id: int) -> Event | None:
        return self.events.get(event_id)

    def create_event(
        self,
        name: str,
        event_date: date,
        *,
        player_ids: list[int] | None = None,
        game_to: int = DEFAULT_GAME_TO,
        win_by: int = DEFAULT_WIN_BY,
        num_courts: int = DEFAULT_NUM_COURTS,
    ) -> Event:
        event = self.events.create(
            name,
            event_date,
            status=EventStatus.DRAFT,
            game_to=game_to,
            win_by=win_by,
            num_courts=num_courts,
        )
        if player_ids:
            self.events.set_players(event.id, player_ids)
        return event

    def update_event(
        self,
        event_id: int,
        *,
        name: str | None = None,
        event_date: date | None = None,
        status: EventStatus | None = None,
        game_to: int | None = None,
        win_by: int | None = None,
        num_courts: int | None = None,
        player_ids: list[int] | None = None,
    ) -> Event:
        event = self.events.update(
            event_id,
            name=name,
            event_date=event_date,
            status=status,
            game_to=game_to,
            win_by=win_by,
            num_courts=num_courts,
        )
        if player_ids is not None:
            self.events.set_players(event_id, player_ids)
        return event

    def set_status(self, event_id: int, status: EventStatus) -> Event:
        return self.events.update(event_id, status=status)

    def get_attendee_ids(self, event_id: int) -> list[int]:
        return self.events.get_player_ids(event_id)
