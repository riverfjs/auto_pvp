"""Compact engine enums that are shared by data import and battle runtime."""

from __future__ import annotations

from enum import IntEnum, IntFlag, auto


class AbilityFlag(IntFlag):
    """Packed runtime ability flags. Parameterized bonuses use fixed fields."""

    NONE = 0
    BARREL_ACTIVE = auto()
    REVIVE = auto()
    FAKE_DEATH = auto()
    COST_INVERT = auto()
    ENERGY_NO_CAP = auto()
    BURN_NO_DECAY = auto()
    EXTRA_POISON_TICK = auto()


class StatusFlag(IntFlag):
    NONE = 0; BURN = auto(); POISON = auto(); FREEZE = auto(); LEECH = auto()


class StatusType(IntEnum):
    BURN = 0; POISON = 1; FREEZE = 2; LEECH = 3

    @property
    def flag(self) -> StatusFlag:
        return StatusFlag(1 << self.value)


class SkillCategory(IntEnum):
    PHYSICAL = 1; MAGICAL = 2; DEFENSE = 3; STATUS = 4


class Stats(IntEnum):
    HP = 0; ATK_PHYS = 1; ATK_MAG = 2; DEF_PHYS = 3; DEF_MAG = 4; SPEED = 5


class WeatherType(IntEnum):
    NONE = 0; RAIN = 1; SANDSTORM = 2; SNOW = 3


class Element(IntEnum):
    """Roco 18-element system for per-element skill count packing."""

    NORMAL = 0; GRASS = 1; FIRE = 2; WATER = 3; LIGHT = 4; GROUND = 5
    ICE = 6; DRAGON = 7; ELECTRIC = 8; POISON = 9; BUG = 10; FIGHTING = 11
    FLYING = 12; CUTE = 13; GHOST = 14; DARK = 15; MECHANICAL = 16; ILLUSION = 17

    @classmethod
    def from_str(cls, s: str) -> "Element":
        mapping = {
            "普通": cls.NORMAL, "草": cls.GRASS, "火": cls.FIRE, "水": cls.WATER,
            "光": cls.LIGHT, "地": cls.GROUND, "地面": cls.GROUND,
            "冰": cls.ICE, "龙": cls.DRAGON, "电": cls.ELECTRIC, "毒": cls.POISON,
            "虫": cls.BUG, "武": cls.FIGHTING, "格斗": cls.FIGHTING,
            "翼": cls.FLYING, "飞行": cls.FLYING, "萌": cls.CUTE,
            "幽": cls.GHOST, "幽灵": cls.GHOST, "恶": cls.DARK,
            "机械": cls.MECHANICAL,
            "幻": cls.ILLUSION, "超能": cls.ILLUSION,
        }
        token = s.replace("系", "").strip()
        if token in {"岩", "岩石", "钢", "Rock", "ROCK", "rock", "Steel", "STEEL", "steel"}:
            raise ValueError(f"legacy element is not supported: {s!r}")
        try:
            return mapping[token]
        except KeyError as exc:
            raise ValueError(f"unknown element: {s!r}") from exc


ELEMENT_NAMES: tuple[str, ...] = (
    "普通", "草", "火", "水", "光", "地", "冰", "龙", "电",
    "毒", "虫", "武", "翼", "萌", "幽", "恶", "机械", "幻",
)


def normalize_element_name(value: str) -> str:
    """Normalize structured element input to the canonical Roco Chinese name."""

    return ELEMENT_NAMES[Element.from_str(value).value]
