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

    # --- Kernel-specific ops (3xxx range, no pak collision) -----------------
    # These are effect primitives consumed by the fixed kernel op table.
    # They bridge old TAG_* ids to PakOp-native dispatch.
    DAMAGE = 3001
    HEAL_HP = 3002
    HEAL_ENERGY = 3003
    STEAL_ENERGY = 3004
    ENEMY_LOSE_ENERGY = 3005
    LIFE_DRAIN = 3006
    SELF_BUFF = 3007
    SELF_DEBUFF = 3008
    ENEMY_DEBUFF = 3009
    BURN = 3010
    POISON = 3011
    FREEZE = 3012
    DAMAGE_REDUCTION = 3014
    ENERGY_ALL_IN = 3016
    WEATHER = 3017
    COUNTER_ATTACK = 3018
    GRANT_LIFE_DRAIN = 3025
    POISON_MARK = 3027
    MOISTURE_MARK = 3028
    DRAGON_MARK = 3029
    WIND_MARK = 3030
    CHARGE_MARK = 3031
    SOLAR_MARK = 3032
    ATTACK_MARK = 3033
    SLOW_MARK = 3034
    SLUGGISH_MARK = 3035
    SPIRIT_MARK = 3036
    METEOR_MARK = 3037
    THORN_MARK = 3038
    MOMENTUM_MARK = 3039
    DISPEL_ENEMY_MARKS = 3040
    CONSUME_MARKS_HEAL = 3043
    STEAL_MARKS = 3045
    FORCE_ENEMY_SWITCH = 3047
    AGILITY = 3048
    INTERRUPT = 3049
    POWER_DYNAMIC = 3050
    PERMANENT_MOD = 3052
    SKILL_MOD = 3053
    NEXT_ATTACK_MOD = 3054
    CLEANSE = 3055
    PASSIVE_ENERGY_REDUCE = 3060
    CONVERT_POISON_TO_MARK = 3062
    DISPEL_MARKS = 3063
    DISPEL_BUFFS = 3065
    DISPEL_DEBUFFS = 3066
    ENEMY_ENERGY_COST_UP = 3068
    TRANSFER_MODS = 3072
    COUNTER_ACCUMULATE_TRANSFORM = 3076
    MIRROR_ENEMY_BUFFS = 3080
    COUNTER_SUCCESS_SPEED_PRIORITY = 3088
    FIRST_STRIKE_POWER_BONUS = 3089
    FIRST_STRIKE_HIT_COUNT = 3090
    AUTO_SWITCH_ON_ZERO_ENERGY = 3092
    AUTO_SWITCH_AFTER_ACTION = 3093
    TEAM_SYNERGY_BUG_SWARM_ATTACK = 3094
    STAT_SCALE_HITS_PER_HP_LOST = 3099
    DAMAGE_MOD_NON_STAB = 3106
    DAMAGE_MOD_NON_LIGHT = 3107
    DAMAGE_MOD_NON_WEAKNESS = 3108
    DAMAGE_MOD_POLLUTANT_BLOOD = 3109
    DAMAGE_MOD_LEADER_BLOOD = 3110
    HEAL_ON_GRASS_SKILL = 3113
    SKILL_COST_REDUCTION_TYPE = 3114
    POISON_ON_SKILL_APPLY = 3116
    ON_SKILL_ELEMENT_BUFF = 3119
    ON_SKILL_ELEMENT_POISON = 3120
    ON_SKILL_ELEMENT_COST_REDUCE = 3121
    ON_SKILL_ELEMENT_ENEMY_ENERGY = 3123
    CARRY_SKILL_POWER_BONUS = 3124
    CARRY_SKILL_COST_REDUCE = 3125
    ENEMY_ALL_COST_UP = 3131
    LEAVE_HEAL_ALLY = 3133
    LEAVE_ENERGY_REFILL = 3135
    STEAL_ALL_ENEMY_ENERGY = 3136
    ENEMY_SWITCH_SELF_COST_REDUCE = 3138
    ON_INTERRUPT_COOLDOWN = 3139
    LOW_COST_SKILL_POWER_BONUS = 3140
    SPECIFIC_SKILL_POWER_BONUS = 3144
    HP_FOR_ENERGY = 3146
    ON_SUPER_EFFECTIVE_BUFF = 3150
    HIT_COUNT_PER_POISON = 3153
    ENTRY_SELF_DAMAGE = 3161
    ENERGY_DRAIN_BY_COST_DIFF = 3162
    ENTRY_BUFF_PER_SKILL_COUNT = 3163
    DEVOTION_GRANT_RANDOM = 3174
    CHARGE_COST_REDUCE = 3178
    CONTRACT_ENTRY = 3181
    BLOODLINE_ENTRY = 3182
    CUTE_GAIN = 3183
    CUTE_ENEMY_GAIN = 3184
    CUTE_BOTH = 3186
    CUTE_TRANSFER = 3187
    CUTE_CLEAR_SELF = 3188
    CUTE_IF_POWER_BONUS = 3189
    CUTE_ON_GAIN_POWER_PERM = 3190
    CUTE_ON_GAIN_COST_REDUCE = 3191
    CUTE_ON_GAIN_SPEED_PERM = 3192
    CUTE_TEAM_POWER = 3193
    CUTE_LETHAL_SHIELD = 3194
    CUTE_HIT_PER_STACK = 3196
    CUTE_BENCH_COST_REDUCE = 3197
    ON_SKILL_ELEMENT_BURN = 3198
    ON_SKILL_ELEMENT_FREEZE = 3199
    ON_SKILL_ELEMENT_HIT_COUNT = 3200
    ENTRY_ENERGY_FROM_ELEMENT_COUNT = 3202
    ENTRY_ENERGY_FROM_COUNTER_COUNT = 3203
    EXCHANGE_MOVES = 3204
    EXCHANGE_HP_RATIO = 3205
    BORROW_TEAM_SKILL = 3206
    HIT_COUNT_DELTA = 3207
    ANTI_HEAL = 3210
    POWER_BY_STATUS_COUNT_ELEMENTS = 3212
    DEBUFF_EXTRA_LAYERS = 3213
    POWER_MULTIPLIER_BUFF = 3214


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
