"""Compiled effect primitives and trigger timings (pak-native edition).

This module replaces the hand-crafted EffectTag enum with PakOp, whose values
are buff_base_id prefix families (first 4 digits) drawn directly from pak game
data.  Three synthetic EFFECT_CONF types round out the enum for non-buff
effects.

Timing values map 1:1 to pak cast_moment integers -- no translation layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from types import MappingProxyType
from typing import Any


EMPTY_PARAMS = MappingProxyType({})


# ---------------------------------------------------------------------------
# PakOp -- replaces EffectTag
# ---------------------------------------------------------------------------
# Values are buff_base_id prefix families (buff_base_id // 1000) for BUFF_CONF
# effects, and 10001-10003 for the three EFFECT_CONF types.

class PakOp(IntEnum):
    """Pak-native operation codes derived from buff_base_id prefix families."""

    UNSUPPORTED = 0

    # --- buff_base_id prefix families (94 active) sorted by usage -----------
    STAT_MOD = 2001
    IMMUNITY_LOCK = 2003
    POWER_MOD = 2023
    ON_HIT_REACTION = 2019
    DAMAGE_REDUCE = 2011
    STUN_HEAL = 2017
    COST_MOD = 2032
    ELEMENT_TRIGGER = 2035
    STATUS_CONDITION = 2007
    DETECTION = 2040
    CONDITIONAL_TRIGGER = 2064
    FORCE_SWITCH = 2048
    COUNTER_REWARD = 2067
    MARK_METEOR = 2094
    CHAR_SPECIFIC_A = 2063
    ENTRY_FIRST_TURN = 2093
    SLOT_MOD = 2117
    ON_KILL = 2046
    DRIVE = 2115
    BORROW = 2132
    MARK_CHANGE = 2143
    SURVIVAL = 2038
    HIT_COUNT = 2045
    CUTE_SPEED = 2102
    NEXT_PET = 2010
    COND_POWER = 2107
    CHARGE = 2088
    LOCK_SWITCH = 2004
    SLOT_PRIORITY = 2077
    FREEZE_LOCK = 2092
    CANDY = 2142
    BOSS_STUN = 2006
    EARTH_HEART = 2024
    EFFICIENCY = 2037
    FREEZE_STATUS = 2058
    POISON_FANG = 2068
    PRIORITY = 2021
    HP_CONDITIONAL = 2041
    TURN_END_TRANSFORM = 2049
    SKILL_COPY = 2056
    TEAM_ON_DEATH = 2073
    DOUBLE_TRIGGER = 2075
    REFRACT = 2089
    MAGIC_KILLER = 2104
    DOUBLE_ACTION = 2015
    ENERGY_GAIN = 2052
    HEAL_MOD = 2053
    DYNAMIC_HIT = 2091
    PURIFY = 2138
    ELEMENT_ENERGY = 2100
    SKILL_CHECK = 2105
    FLAT_POWER = 2108
    DRAIN = 2054
    CHAR_SPECIFIC_B = 2086
    CAP_RAISE = 2114
    ALERT = 2130
    CUTE_INFINITE = 2136
    LEECH = 2005
    NUTRITION = 2022
    MOMENTUM = 2027
    FIRE_RAGE = 2029
    ENTRY_AMBUSH = 2033
    OVERLOAD = 2034
    QUICK_START = 2043
    ENTRY_STATUS = 2050
    DREAM = 2051
    DARK_HEAL = 2071
    SLEEPWALK = 2076
    FEYNMAN = 2084
    POSITION_COST = 2106
    BURN_REVERSE = 2111
    TEST = 2121
    FROG = 2133
    ELEMENT_VULN = 2025
    TEST_28 = 2028
    DUCK = 2039
    NON_SE_REDUCE = 2042
    COOLDOWN = 2062
    OTTER = 2072
    LANTERN = 2079
    CYCLOPS = 2080
    MIRROR_PRIORITY = 2083
    ENERGY_HEAL = 2087
    EXTEND_ENTRY = 2101
    DIFF_SKILL_COST = 2103
    OVERFLOW_HEAL = 2109
    MARK_NO_DECAY = 2110
    COVER = 2112
    RETURN = 2118
    FIRST_USE_POWER = 2119
    SIDE_COST = 2120
    SEGMENT_HP = 2134
    HIT_BURN = 2135
    COST_EFFICIENCY = 2141

    # --- EFFECT_CONF synthetic types ----------------------------------------
    EFF_BUFF_APPLY = 10001   # EFFECT_CONF type=1: buff application
    EFF_DAMAGE = 10002       # EFFECT_CONF type=2: damage effect
    EFF_STATE_CHANGE = 10003 # EFFECT_CONF type=3: state change / dispel

    # (end of PakOp — kernel uses handler indices from effect_codegen, not PakOp values)


# ---------------------------------------------------------------------------
# Timing -- values match pak cast_moment directly
# ---------------------------------------------------------------------------

class Timing(IntEnum):
    """Effect trigger points matching pak cast_moment values."""

    CALC_DAMAGE = 6       # pre-attack setup
    CHECK_HIT = 7         # post-hit
    FAINT = 9             # faint trigger
    TURN_START = 10       # turn start
    AFTER_MOVE = 11       # main effect resolution
    TURN_END = 12         # end of turn
    PASSIVE_PERSIST = 23  # passive persistent
    SWITCH_IN = 24        # switch in
    CHARGE = 25           # charge/prep
    PASSIVE_COND = 26     # passive conditional
    BATTLE_START = 27     # entry aura


# ---------------------------------------------------------------------------
# Dataclasses -- updated to use PakOp
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class EffectSpec:
    """Compiled effect primitive from data storage."""

    tag: PakOp
    timing: Timing
    params: MappingProxyType[str, Any] = EMPTY_PARAMS
    chance: float = 1.0
    condition: str = ""


@dataclass(slots=True)
class SkillEffect:
    skill_id: int
    effect: EffectSpec
    sort_order: int = 0


@dataclass(slots=True)
class AbilityEffect:
    ability_id: int
    effect: EffectSpec
    sort_order: int = 0
