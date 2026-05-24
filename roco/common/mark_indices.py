"""Pure mark/devotion lane indices shared by compiler and runtime."""

from __future__ import annotations

from enum import IntEnum


class MarkIdx(IntEnum):
    MOISTURE = 0
    DRAGON = 1
    MOMENTUM = 2
    WIND = 3
    CHARGE = 4
    SOLAR = 5
    ATTACK = 6
    SLOW = 7
    SPIRIT = 8
    METEOR = 9
    POISON = 10
    THORN = 11
    SLUGGISH = 12


class DevotionIdx(IntEnum):
    JIAMEI = 0
    FEIDUAN = 1
    CHONGJIAN = 2
    KUNFU = 3
    CHONGQUN = 4
