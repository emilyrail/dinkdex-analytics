"""Player orchestration."""

from __future__ import annotations

from analytics.elo import is_provisional
from models.player import Player
from repositories.players import PlayerRepository
from utils.config import INITIAL_ELO


class PlayerService:
    def __init__(self, players: PlayerRepository | None = None) -> None:
        self.players = players or PlayerRepository()

    def list_players(self, *, active_only: bool = False) -> list[Player]:
        return self.players.list_players(active_only=active_only)

    def games_played_counts(self) -> dict[int, int]:
        return self.players.games_played_counts()

    def is_provisional_player(self, player_id: int, games: int | None = None) -> bool:
        if games is None:
            games = self.games_played_counts().get(player_id, 0)
        return is_provisional(games)

    def create_player(
        self,
        name: str,
        *,
        display_name: str | None = None,
        active: bool = True,
    ) -> Player:
        existing = self.players.find_by_name(name)
        if existing is not None:
            raise ValueError(f"Player '{name}' already exists")
        return self.players.create(
            name,
            display_name=display_name,
            active=active,
            current_elo=INITIAL_ELO,
        )

    def update_player(
        self,
        player_id: int,
        *,
        name: str | None = None,
        display_name: str | None = None,
        active: bool | None = None,
    ) -> Player:
        if name is not None:
            other = self.players.find_by_name(name)
            if other is not None and other.id != player_id:
                raise ValueError(f"Player '{name}' already exists")
        return self.players.update(
            player_id,
            name=name,
            display_name=display_name,
            active=active,
        )
