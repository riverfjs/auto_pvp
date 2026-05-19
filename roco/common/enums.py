"""Domain enums shared across data, compiler, and engine layers."""

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
    HP_FOR_ENERGY = auto()
    BURN_NO_DECAY = auto()
    EXTRA_POISON_TICK = auto()
    EXTRA_FREEZE_ON_FREEZE = auto()
    CUTE_LETHAL_SHIELD = auto()
    KILL_MP_PENALTY = auto()
    SKILL_SLOT_LOCK = auto()
    IMMUNE_ZERO_ENERGY_ATTACKER = auto()
    IMMUNE_LOW_COST_ATTACK = auto()
    FIXED_HIT_COUNT_ALL = auto()
    START_ZERO_ENERGY = auto()
    TURN_END_SKIP = auto()
    COPY_SWITCH_STATE = auto()
    HEAL_ON_BURN_DAMAGE = auto()
    HEAL_ON_POISON_DAMAGE = auto()
    CUTE_NO_CAP = auto()
    MARK_STACK_NO_REPLACE = auto()
    SHARE_GAINS = auto()
    SHUFFLE_SKILLS_REDUCE_LAST = auto()
    HALF_METEOR_FULL_DAMAGE = auto()
    CHARGE_FREE_SKILL = auto()
    FIRST_ACTION_EXTRA_USE = auto()
    BUFF_EXTRA_LAYERS = auto()
    HEAL_HP_PER_ENERGY_GAIN = auto()
    BURST_EXTEND = auto()


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
            "光": cls.LIGHT, "地": cls.GROUND, "冰": cls.ICE, "龙": cls.DRAGON,
            "电": cls.ELECTRIC, "毒": cls.POISON, "虫": cls.BUG, "武": cls.FIGHTING,
            "翼": cls.FLYING, "萌": cls.CUTE, "幽": cls.GHOST, "恶": cls.DARK,
            "机械": cls.MECHANICAL, "幻": cls.ILLUSION,
        }
        try:
            return mapping[s.strip()]
        except KeyError as exc:
            raise ValueError(f"unknown element: {s!r}") from exc


ELEMENT_NAMES: tuple[str, ...] = (
    "普通", "草", "火", "水", "光", "地", "冰", "龙", "电",
    "毒", "虫", "武", "翼", "萌", "幽", "恶", "机械", "幻",
)


def normalize_element_name(value: str) -> str:
    """Normalize structured element input to the canonical Roco Chinese name."""

    return ELEMENT_NAMES[Element.from_str(value).value]
