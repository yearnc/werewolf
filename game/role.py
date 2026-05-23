"""Role definitions for the Werewolf game."""

from __future__ import annotations

from enum import Enum


class Role(Enum):
    WEREWOLF = "werewolf"
    SEER = "seer"
    WITCH = "witch"
    HUNTER = "hunter"
    VILLAGER = "villager"


class Team(Enum):
    GOOD = "good"
    EVIL = "evil"


ROLE_DISPLAY: dict[Role, str] = {
    Role.WEREWOLF: "狼人",
    Role.SEER: "预言家",
    Role.WITCH: "女巫",
    Role.HUNTER: "猎人",
    Role.VILLAGER: "村民",
}

ROLE_ABILITY: dict[Role, str] = {
    Role.WEREWOLF: "每晚可以和狼队友一起选择一名玩家击杀。你知道其他狼人是谁。",
    Role.SEER: "每晚可以查验一名玩家的身份（狼人或好人）。",
    Role.WITCH: "拥有一瓶解药（可救人）和一瓶毒药（可毒人），每夜最多使用一瓶。",
    Role.HUNTER: "被投票放逐或狼人击杀时，可以开枪带走一名玩家同归于尽（被毒杀则不能开枪）。",
    Role.VILLAGER: "没有特殊技能，依靠推理和投票找出狼人。",
}

DEFAULT_ROLES: list[Role] = [
    Role.WEREWOLF,
    Role.WEREWOLF,
    Role.WEREWOLF,
    Role.SEER,
    Role.WITCH,
    Role.HUNTER,
    Role.VILLAGER,
    Role.VILLAGER,
    Role.VILLAGER,
]


def get_team(role: Role) -> Team:
    if role == Role.WEREWOLF:
        return Team.EVIL
    return Team.GOOD


def get_team_display(role: Role) -> str:
    return "狼人阵营" if get_team(role) == Team.EVIL else "好人阵营"
