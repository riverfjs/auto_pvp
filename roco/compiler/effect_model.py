"""Compiled effect primitives and trigger timings.

This module is intentionally separate from runtime state. The hot battle
state stores compact ids and packed flags; effect definitions are immutable
catalog rows loaded before simulation.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum, IntFlag, auto
from types import MappingProxyType
from typing import Any


EMPTY_PARAMS = MappingProxyType({})


class EffectFlag(IntFlag):
    NONE = 0; DRAIN = auto(); HEAL_HP = auto(); HEAL_ENERGY = auto()
    STEAL_ENERGY = auto(); DEFENSE = auto(); BURN = auto(); POISON = auto()
    FREEZE = auto(); LEECH = auto(); STAT_CHANGE = auto(); FORCE_SWITCH = auto()
    CHARGE = auto(); ENERGY_ALL_IN = auto(); WEATHER = auto(); COUNTER = auto()
    CONDITIONAL = auto(); MIRROR_DAMAGE = auto(); ENEMY_COST_UP = auto()
    HP_FOR_ENERGY = auto(); PERMANENT_MOD = auto(); PURE_DAMAGE = auto()
    BURST = auto(); AGILITY = auto(); IS_MARK = auto(); DEVOTION = auto()


class Timing(IntEnum):
    """Effect trigger points stored as compact integer codes."""

    PASSIVE = 0
    BATTLE_START = 1
    TURN_START = 2
    BEFORE_MOVE = 3
    ON_DAMAGE = 4
    AFTER_MOVE = 5
    TURN_END = 6
    SWITCH_IN = 7
    SWITCH_OUT = 8
    FAINT = 9
    KILL = 10
    COUNTER_SUCCESS = 11
    CHECK_HIT = 12
    CALC_DAMAGE = 13
    ADJUST_DAMAGE = 14
    APPLY_DAMAGE = 15
    TAKE_DAMAGE = 16
    ENEMY_SWITCH = 17
    ALLY_COUNTER = 18
    BE_KILLED = 19
    USE_SKILL = 20


class EffectTag(IntEnum):
    """Project-owned primitive ids used by unified effect rows."""

    UNSUPPORTED = 0
    DAMAGE = 1
    HEAL_HP = 2
    HEAL_ENERGY = 3
    STEAL_ENERGY = 4
    ENEMY_LOSE_ENERGY = 5
    LIFE_DRAIN = 6
    SELF_BUFF = 7
    ENEMY_DEBUFF = 8
    BURN = 9
    POISON = 10
    FREEZE = 11
    LEECH = 12
    METEOR = 13
    DAMAGE_REDUCTION = 14
    FORCE_SWITCH = 15
    ENERGY_ALL_IN = 16
    WEATHER = 17
    COUNTER_ATTACK = 18
    COUNTER_STATUS = 19
    COUNTER_DEFENSE = 20
    BARREL_STATE = 21
    BURST_POWER_BONUS = 22
    FAINT_NO_MP_LOSS = 23
    ENERGY_REGEN_PER_TURN = 24
    GRANT_LIFE_DRAIN = auto()
    SELF_DEBUFF = auto()
    POISON_MARK = auto()
    MOISTURE_MARK = auto()
    DRAGON_MARK = auto()
    WIND_MARK = auto()
    CHARGE_MARK = auto()
    SOLAR_MARK = auto()
    ATTACK_MARK = auto()
    SLOW_MARK = auto()
    SLUGGISH_MARK = auto()
    SPIRIT_MARK = auto()
    METEOR_MARK = auto()
    THORN_MARK = auto()
    MOMENTUM_MARK = auto()
    DISPEL_ENEMY_MARKS = auto()
    CONVERT_MARKS_TO_BURN = auto()
    DISPEL_MARKS_TO_BURN = auto()
    CONSUME_MARKS_HEAL = auto()
    MARKS_TO_METEOR = auto()
    STEAL_MARKS = auto()
    ENERGY_COST_PER_ENEMY_MARK = auto()
    FORCE_ENEMY_SWITCH = auto()
    AGILITY = auto()
    INTERRUPT = auto()
    POWER_DYNAMIC = auto()
    ENERGY_COST_DYNAMIC = auto()
    PERMANENT_MOD = auto()
    SKILL_MOD = auto()
    NEXT_ATTACK_MOD = auto()
    CLEANSE = auto()
    SELF_KO = auto()
    RESET_SKILL_COST = auto()
    POSITION_BUFF = auto()
    DRIVE = auto()
    PASSIVE_ENERGY_REDUCE = auto()
    CONVERT_BUFF_TO_POISON = auto()
    CONVERT_POISON_TO_MARK = auto()
    DISPEL_MARKS = auto()
    CONDITIONAL_BUFF = auto()
    DISPEL_BUFFS = auto()
    DISPEL_DEBUFFS = auto()
    MIRROR_DAMAGE = auto()
    ENEMY_ENERGY_COST_UP = auto()
    COUNTER_OVERRIDE = auto()
    ABILITY_COMPUTE = auto()
    ABILITY_INCREMENT_COUNTER = auto()
    TRANSFER_MODS = auto()
    BURN_NO_DECAY = auto()
    POWER_MULTIPLIER_BUFF = auto()
    THREAT_SPEED_BUFF = auto()
    COUNTER_ACCUMULATE_TRANSFORM = auto()
    DELAYED_REVIVE = auto()
    COPY_SWITCH_STATE = auto()
    COST_INVERT = auto()
    MIRROR_ENEMY_BUFFS = auto()
    REPLAY_AGILITY = auto()
    ENERGY_COST_ACCUMULATE = auto()
    AGILITY_COST_SHARE = auto()
    COUNTER_SUCCESS_DOUBLE_DAMAGE = auto()
    COUNTER_SUCCESS_BUFF_PERMANENT = auto()
    COUNTER_SUCCESS_POWER_BONUS = auto()
    COUNTER_SUCCESS_COST_REDUCE = auto()
    COUNTER_SUCCESS_SPEED_PRIORITY = auto()
    FIRST_STRIKE_POWER_BONUS = auto()
    FIRST_STRIKE_HIT_COUNT = auto()
    FIRST_STRIKE_AGILITY = auto()
    AUTO_SWITCH_ON_ZERO_ENERGY = auto()
    AUTO_SWITCH_AFTER_ACTION = auto()
    TEAM_SYNERGY_BUG_SWARM_ATTACK = auto()
    TEAM_SYNERGY_BUG_SWARM_INSPIRE = auto()
    TEAM_SYNERGY_BRAVE_IF_BUGS = auto()
    TEAM_SYNERGY_BUG_KILL_AFF = auto()
    STAT_SCALE_DEFENSE_PER_ENERGY = auto()
    STAT_SCALE_HITS_PER_HP_LOST = auto()
    STAT_SCALE_ATTACK_DECAY = auto()
    STAT_SCALE_METEOR_MARKS_PER_TURN = auto()
    MARK_POWER_PER_METEOR = auto()
    MARK_FREEZE_TO_METEOR = auto()
    MARK_STACK_NO_REPLACE = auto()
    MARK_STACK_DEBUFFS = auto()
    DAMAGE_MOD_NON_STAB = auto()
    DAMAGE_MOD_NON_LIGHT = auto()
    DAMAGE_MOD_NON_WEAKNESS = auto()
    DAMAGE_MOD_POLLUTANT_BLOOD = auto()
    DAMAGE_MOD_LEADER_BLOOD = auto()
    DAMAGE_RESIST_SAME_TYPE = auto()
    HEAL_PER_TURN = auto()
    HEAL_ON_GRASS_SKILL = auto()
    SKILL_COST_REDUCTION_TYPE = auto()
    POISON_STAT_DEBUFF = auto()
    POISON_ON_SKILL_APPLY = auto()
    FREEZE_IMMUNITY_AND_BUFF = auto()
    EXTRA_FREEZE_ON_FREEZE = auto()
    ON_SKILL_ELEMENT_BUFF = auto()
    ON_SKILL_ELEMENT_POISON = auto()
    ON_SKILL_ELEMENT_COST_REDUCE = auto()
    ON_SKILL_ELEMENT_HEAL = auto()
    ON_SKILL_ELEMENT_ENEMY_ENERGY = auto()
    CARRY_SKILL_POWER_BONUS = auto()
    CARRY_SKILL_COST_REDUCE = auto()
    CARRY_ELEMENT_COUNT_BUFF = auto()
    ON_KILL_BUFF = auto()
    RECOIL_DAMAGE = auto()
    ENTRY_BUFF = auto()
    ON_ENTER_GRANT_DRAIN = auto()
    ENEMY_ALL_COST_UP = auto()
    ENTRY_FREEZE_EXTRA = auto()
    LEAVE_HEAL_ALLY = auto()
    LEAVE_BUFF_ALLY = auto()
    LEAVE_ENERGY_REFILL = auto()
    STEAL_ALL_ENEMY_ENERGY = auto()
    ENEMY_SWITCH_DEBUFF = auto()
    ENEMY_SWITCH_SELF_COST_REDUCE = auto()
    ON_INTERRUPT_COOLDOWN = auto()
    LOW_COST_SKILL_POWER_BONUS = auto()
    ENERGY_COST_CONDITION_BUFF = auto()
    ENEMY_TECH_TOTAL_POWER = auto()
    HALF_METEOR_FULL_DAMAGE = auto()
    SPECIFIC_SKILL_POWER_BONUS = auto()
    ENERGY_NO_CAP = auto()
    HP_FOR_ENERGY = auto()
    SHUFFLE_SKILLS_REDUCE_LAST = auto()
    WEATHER_CONDITIONAL_BUFF = auto()
    FAINTED_ALLIES_BUFF = auto()
    ON_SUPER_EFFECTIVE_BUFF = auto()
    ENEMY_ELEMENT_DIVERSITY_POWER = auto()
    KILL_MP_PENALTY = auto()
    HIT_COUNT_PER_POISON = auto()
    FIRST_ACTION_HIT_BONUS = auto()
    FIXED_HIT_COUNT_ALL = auto()
    EXTRA_POISON_TICK = auto()
    CONDITIONAL_ENTRY_BUFF_TOTAL_COST = auto()
    CONDITIONAL_ENTRY_BUFF_MP = auto()
    IMMUNE_ZERO_ENERGY_ATTACKER = auto()
    IMMUNE_LOW_COST_ATTACK = auto()
    ENTRY_SELF_DAMAGE = auto()
    ENERGY_DRAIN_BY_COST_DIFF = auto()
    ENTRY_BUFF_PER_SKILL_COUNT = auto()
    TURN_END_REPEAT = auto()
    TURN_END_SKIP = auto()
    COST_CHANGE_DOUBLE = auto()
    NOISE_DEBUFF = auto()
    SKILL_SLOT_LOCK = auto()
    BUFF_EXTRA_LAYERS = auto()
    BURST_ENEMY_COST_UP = auto()
    BURST_ELEMENT_COST_REDUCE = auto()
    BURST_EXTEND = auto()
    DEVOTION_GRANT = auto()
    DEVOTION_GRANT_RANDOM = auto()
    DEVOTION_ON_HIT = auto()
    DRIVE_POSITION_SHIFT = auto()
    DRIVE_ON_POSITION_CHANGE = auto()
    CHARGE_COST_REDUCE = auto()
    CHARGE_FREE_SKILL = auto()
    SHARE_GAINS = auto()
    CONTRACT_ENTRY = auto()
    BLOODLINE_ENTRY = auto()
    CUTE_GAIN = auto()
    CUTE_ENEMY_GAIN = auto()
    CUTE_ALL_BENCH = auto()
    CUTE_BOTH = auto()
    CUTE_TRANSFER = auto()
    CUTE_CLEAR_SELF = auto()
    CUTE_IF_POWER_BONUS = auto()
    CUTE_ON_GAIN_POWER_PERM = auto()
    CUTE_ON_GAIN_COST_REDUCE = auto()
    CUTE_ON_GAIN_SPEED_PERM = auto()
    CUTE_TEAM_POWER = auto()
    CUTE_LETHAL_SHIELD = auto()
    CUTE_NO_CAP = auto()
    CUTE_HIT_PER_STACK = auto()
    CUTE_BENCH_COST_REDUCE = auto()
    ON_SKILL_ELEMENT_BURN = auto()
    ON_SKILL_ELEMENT_FREEZE = auto()
    ON_SKILL_ELEMENT_HIT_COUNT = auto()
    START_ZERO_ENERGY = auto()
    ENTRY_ENERGY_FROM_ELEMENT_COUNT = auto()
    ENTRY_ENERGY_FROM_COUNTER_COUNT = auto()
    EXCHANGE_MOVES = auto()
    EXCHANGE_HP_RATIO = auto()
    BORROW_TEAM_SKILL = auto()
    HIT_COUNT_DELTA = auto()
    HEAL_ON_BURN_DAMAGE = auto()
    HEAL_ON_POISON_DAMAGE = auto()
    ANTI_HEAL = auto()
    FIRST_ACTION_EXTRA_USE = auto()
    POWER_BY_STATUS_COUNT_ELEMENTS = auto()
    DEBUFF_EXTRA_LAYERS = auto()
    HEAL_HP_PER_ENERGY_GAIN = auto()


@dataclass(slots=True)
class EffectSpec:
    """Compiled effect primitive from data storage."""

    tag: EffectTag
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
