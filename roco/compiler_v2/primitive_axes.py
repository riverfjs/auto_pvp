"""Resolve pak axes to compiler primitive keys.

This module is intentionally independent of ``roco.engine``.  It translates
pak/Lua axis symbols into pak-derived primitive keys; the engine later binds
those keys to concrete kernel handlers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from roco.common.primitive_keys import buff_type_key, mark_note_key


@dataclass(frozen=True)
class ResolvedPrimitiveAxes:
    """Pak axes resolved to primitive strings."""

    buffbase_order: dict[int, str]
    prefix: dict[int, str]
    base_id: dict[int, str]
    prefix_aliases: dict[int, str]
    raw: dict[str, dict[int | str, tuple[str, str]]]


# Compiler coverage allowlist for pak BuffType axes.  The value is a debug
# alias only; emitted primitive keys are always ``buff_type:<symbol>`` and the
# engine owns the key -> op binding.
BUFF_TYPE_ALIASES: dict[str, str] = {
    "BFT_ABSORB": "LEECH",
    "BFT_ASSIGN_ATTACK_FIRST": "QUICK_START",
    "BFT_ATTR_CHANGE": "STAT_MOD",
    "BFT_BAN": "LOCK_SWITCH",
    "BFT_BLOOD": "DRAIN",
    "BFT_BLOOD_TO_ENERGY": "EARTH_HEART",
    "BFT_BUFF_AFTER_SKILL": "ELEMENT_TRIGGER",
    "BFT_BUFF_BY_HEAL": "NUTRITION",
    "BFT_BUFF_LAYER_CHANGE": "EFFICIENCY",
    "BFT_CAST_REPEAT_SKILL": "DOUBLE_ACTION",
    "BFT_CAST_SKILL_AFTER_ATTACK": "ON_HIT_REACTION",
    "BFT_CHANGE_CATCH_VALUE": "ENTRY_AMBUSH",
    "BFT_CHANGE_GAIN_ENERGY_EFFECIENCY": "OVERLOAD",
    "BFT_CHANGE_SDT_RATIO": "NON_SE_REDUCE",
    "BFT_CHANGE_SKILL_ENERGY_COST": "COST_MOD",
    "BFT_CHECK_HP": "HP_CONDITIONAL",
    "BFT_CURRENT_ENERGY": "ENERGY_GAIN",
    "BFT_DAM": "STATUS_CONDITION",
    "BFT_DETECT_ENEMY_SKILLS": "DREAM",
    "BFT_EIGHTY": "CYCLOPS",
    "BFT_EIGHTY_EIGHT": "CHARGE",
    "BFT_EIGHTY_FOUR": "FEYNMAN",
    "BFT_EIGHTY_NINE": "REFRACT",
    "BFT_EIGHTY_SEVEN": "ENERGY_HEAL",
    "BFT_EIGHTY_SIX": "CHAR_SPECIFIC_B",
    "BFT_EIGHTY_THREE": "MIRROR_PRIORITY",
    "BFT_FIELD_REDUSE_COST": "DUCK",
    "BFT_FIELD_UP_CHANGE": "SURVIVAL",
    "BFT_FREEZE": "FREEZE_STATUS",
    "BFT_INC_DAM_BY_ATTACK_FIRST": "PRIORITY",
    "BFT_INC_DAM_BY_BUFF": "ELEMENT_VULN",
    "BFT_INC_DAM_BY_SKILL": "POWER_MOD",
    "BFT_INC_DAM_BY_TARGET_HP_THRES": "FIRE_RAGE",
    "BFT_NINETY_FOUR": "MARK_METEOR",
    "BFT_NINETY_THREE": "ENTRY_FIRST_TURN",
    "BFT_NINETY_TWO": "FREEZE_LOCK",
    "BFT_NOT_GET_HIT": "MOMENTUM",
    "BFT_O_EIGHT": "FLAT_POWER",
    "BFT_O_EIGHTEEN": "RETURN",
    "BFT_O_ELEVEN": "BURN_REVERSE",
    "BFT_O_FIVE": "SKILL_CHECK",
    "BFT_O_FORTYTWO": "CUTE_CHAIN",
    "BFT_O_FOUR": "MAGIC_KILLER",
    "BFT_O_FOURTEEN": "CAP_RAISE",
    "BFT_O_NINE": "OVERFLOW_HEAL",
    "BFT_O_NINETEEN": "FIRST_USE_POWER",
    "BFT_O_ONE": "EXTEND_ENTRY",
    "BFT_O_SEVEN": "COND_POWER",
    "BFT_O_SEVENTEEN": "SLOT_MOD",
    "BFT_O_SIX": "POSITION_COST",
    "BFT_O_T": "ELEMENT_ENERGY",
    "BFT_O_TEN": "MARK_NO_DECAY",
    "BFT_O_THIRTY": "ALERT",
    "BFT_O_THIRTYSIX": "CUTE_NO_CAP",
    "BFT_O_THIRTYTWO": "BORROW",
    "BFT_O_THREE": "DIFF_SKILL_COST",
    "BFT_O_TWELVE": "COVER",
    "BFT_O_TWENTY": "SIDE_COST",
    "BFT_O_TWENTYONE": "TEST",
    "BFT_O_TWO": "CUTE_SPEED",
    "BFT_PET_TRANSE": "FORCE_SWITCH",
    "BFT_RECORD_CAST_SKILL": "TEST_28",
    "BFT_RELAY": "NEXT_PET",
    "BFT_SEVENTY_FIVE": "DOUBLE_TRIGGER",
    "BFT_SEVENTY_NINE": "LANTERN",
    "BFT_SEVENTY_ONE": "DARK_HEAL",
    "BFT_SEVENTY_SEVEN": "SLOT_PRIORITY",
    "BFT_SEVENTY_SIX": "SLEEPWALK",
    "BFT_SEVENTY_THREE": "TEAM_ON_DEATH",
    "BFT_SEVENTY_TWO": "OTTER",
    "BFT_SIXTY_EIGHT": "POISON_FANG",
    "BFT_SIXTY_SEVEN": "COUNTER_REWARD",
    "BFT_SKILL_ACTUAL_REDUSE_COST": "HEAL_MOD",
    "BFT_SKILL_BAN": "BOSS_STUN",
    "BFT_SKILL_CHANGE": "SKILL_COPY",
    "BFT_SPIKES": "TURN_END_TRANSFORM",
    "BFT_STRENGTHEN_THE_SKILL": "CONDITIONAL_TRIGGER",
    "BFT_TARGET_HAS_BUFF": "CHAR_SPECIFIC_A",
}

# Mixed prefix coverage uses the same pak BuffType symbols; the prefix number
# is derived as 2000 + Enum.BuffType[symbol].
PREFIX_TYPE_ALIASES: dict[str, str] = {
    "BFT_DAMNUM_CHANGE": "DAMAGE_REDUCE",
    "BFT_ENTER_BATTLE": "ENTRY_STATUS",
    "BFT_KILL_BUFF": "ON_KILL",
}

# Mark notes are pak DESC_NOTE_CONF.note strings; values are runtime mark lanes.
MARK_NOTE_MARKS: dict[str, str] = {
    "中毒印记": "POISON",
    "光合印记": "SOLAR",
    "减速印记": "SLOW",
    "攻击印记": "ATTACK",
    "星陨印记": "METEOR",
    "棘刺印记": "THORN",
    "湿润印记": "MOISTURE",
    "蓄势印记": "MOMENTUM",
    "蓄电印记": "CHARGE",
    "降灵印记": "SPIRIT",
    "风起印记": "WIND",
    "龙噬印记": "DRAGON",
}


def resolve_primitive_axes(
    lua_enums: Mapping[str, Mapping[str, int]],
) -> ResolvedPrimitiveAxes:
    """Resolve primitive axis declarations through generated Lua enum data."""

    buff_type_enum = lua_enums.get("BuffType")
    if buff_type_enum is None:
        raise RuntimeError("Lua static bundle is missing Enum.BuffType")

    order_seed: dict[int, str] = {}
    prefix_seed: dict[int, str] = {}
    prefix_aliases: dict[int, str] = {}

    for symbol, alias in BUFF_TYPE_ALIASES.items():
        order = _buff_type_value(buff_type_enum, symbol)
        primitive = buff_type_key(symbol)
        _put_unique(order_seed, order, primitive, f"buff_type={symbol!r}")
        prefix_aliases[2000 + order] = alias

    for symbol, alias in PREFIX_TYPE_ALIASES.items():
        prefix = 2000 + _buff_type_value(buff_type_enum, symbol)
        primitive = buff_type_key(symbol)
        _put_unique(prefix_seed, prefix, primitive, f"prefix_type={symbol!r}")
        prefix_aliases[prefix] = alias

    raw = {
        "buff_type": {
            symbol: (buff_type_key(symbol), alias)
            for symbol, alias in BUFF_TYPE_ALIASES.items()
        },
        "prefix_type": {
            symbol: (buff_type_key(symbol), alias)
            for symbol, alias in PREFIX_TYPE_ALIASES.items()
        },
        "mark_note": {
            note: (mark_note_key(note), mark_name)
            for note, mark_name in MARK_NOTE_MARKS.items()
        },
    }
    return ResolvedPrimitiveAxes(
        buffbase_order=dict(sorted(order_seed.items())),
        prefix=dict(sorted(prefix_seed.items())),
        base_id={},
        prefix_aliases=dict(sorted(prefix_aliases.items())),
        raw=raw,
    )


def _buff_type_value(buff_type_enum: Mapping[str, int], symbol: str) -> int:
    value = buff_type_enum.get(symbol)
    if value is None:
        raise RuntimeError(f"Enum.BuffType has no member {symbol!r}")
    return int(value)


def _put_unique(mapping: dict[int, str], key: int, value: str, context: str) -> None:
    existing = mapping.get(key)
    if existing is not None and existing != value:
        raise RuntimeError(f"{context}: resolved key {key} conflicts: {existing} vs {value}")
    mapping[key] = value
