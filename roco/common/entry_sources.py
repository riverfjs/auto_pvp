"""Shared source-code encoding for switch-in side-count predicates."""

from __future__ import annotations

ENTRY_SOURCE_USED_ELEMENT = 1
ENTRY_SOURCE_COUNTER = 2
ENTRY_SOURCE_STATUS = 3
ENTRY_SOURCE_DEFENSE = 4
ENTRY_SOURCE_EQUIPPED_ELEMENT = 5
ENTRY_SOURCE_ENEMY_SKILL_DAM_TYPE = 6
ENTRY_SOURCE_ENEMY_SWITCH = 7


def entry_source_code(kind: int, element: int = 0) -> int:
    return int(kind) | (max(0, int(element)) << 8)
