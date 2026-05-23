"""Player base class for the Werewolf game."""

from __future__ import annotations


class Player:
    def __init__(self, player_id: int, name: str = ""):
        self.player_id = player_id
        self.name = name or f"玩家{player_id}号"
        self.is_alive = True

    def kill(self) -> None:
        self.is_alive = False

    def __repr__(self) -> str:
        status = "存活" if self.is_alive else "死亡"
        return f"Player({self.player_id}, {self.name}, {status})"
