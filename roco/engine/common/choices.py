"""Compact action, side, and winner primitives."""

from __future__ import annotations

from typing import NamedTuple

ACTION_MOVE = 1
ACTION_SWITCH = 2
ACTION_FOCUS = 3
ACTION_MAGIC = 4
SIDE_A = 0
SIDE_B = 1
NO_WINNER = 0
WIN_A = 1
WIN_B = 2
WIN_DRAW = 3


class Choice(NamedTuple):
    action_code: int
    data: int


def move_choice(skill_index: int) -> Choice:
    return Choice(ACTION_MOVE, skill_index)


def switch_choice(slot_index: int) -> Choice:
    return Choice(ACTION_SWITCH, slot_index)


def focus_choice() -> Choice:
    return Choice(ACTION_FOCUS, 0)


def magic_choice(magic_index: int = 0) -> Choice:
    return Choice(ACTION_MAGIC, magic_index)
