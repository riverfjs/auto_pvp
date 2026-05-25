"""Resolve pak axes to generated audit primitive keys.

This module is intentionally independent of ``roco.engine``.  It translates
pak/Lua axis symbols into pak-derived primitive keys for generated audit
artifacts.  Runtime catalog rows are linked from exact ``effect_ref`` /
``buff_ref`` values instead of this axis map.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from roco.common.primitive_keys import buff_type_key


@dataclass(frozen=True)
class ResolvedPrimitiveAxes:
    """Pak axes resolved to primitive strings."""

    buffbase_order: dict[int, str]
    prefix: dict[int, str]
    base_id: dict[int, str]
    prefix_aliases: dict[int, str]
    raw: dict[str, dict[int | str, str]]


# Compiler coverage allowlist for pak BuffType axes.  Values are the Lua enum
# symbols themselves; no engine aliases are stored here.
BUFF_TYPE_SYMBOLS: tuple[str, ...] = (
    "BFT_ABSORB",
    "BFT_ASSIGN_ATTACK_FIRST",
    "BFT_ATTR_CHANGE",
    "BFT_BAN",
    "BFT_BLOOD",
    "BFT_BLOOD_TO_ENERGY",
    "BFT_BUFF_AFTER_SKILL",
    "BFT_BUFF_BY_HEAL",
    "BFT_BUFF_LAYER_CHANGE",
    "BFT_CAST_REPEAT_SKILL",
    "BFT_CAST_SKILL_AFTER_ATTACK",
    "BFT_CHANGE_CATCH_VALUE",
    "BFT_CHANGE_GAIN_ENERGY_EFFECIENCY",
    "BFT_CHANGE_SDT_RATIO",
    "BFT_CHANGE_SKILL_ENERGY_COST",
    "BFT_CHECK_HP",
    "BFT_CURRENT_ENERGY",
    "BFT_DAM",
    "BFT_DETECT_ENEMY_SKILLS",
    "BFT_EIGHTY",
    "BFT_EIGHTY_EIGHT",
    "BFT_EIGHTY_FOUR",
    "BFT_EIGHTY_NINE",
    "BFT_EIGHTY_SEVEN",
    "BFT_EIGHTY_SIX",
    "BFT_EIGHTY_THREE",
    "BFT_FIELD_REDUSE_COST",
    "BFT_FIELD_UP_CHANGE",
    "BFT_FREEZE",
    "BFT_INC_DAM_BY_ATTACK_FIRST",
    "BFT_INC_DAM_BY_BUFF",
    "BFT_INC_DAM_BY_SKILL",
    "BFT_INC_DAM_BY_TARGET_HP_THRES",
    "BFT_NINETY_FOUR",
    "BFT_NINETY_THREE",
    "BFT_NINETY_TWO",
    "BFT_NOT_GET_HIT",
    "BFT_O_EIGHT",
    "BFT_O_EIGHTEEN",
    "BFT_O_ELEVEN",
    "BFT_O_FIVE",
    "BFT_O_FORTYTWO",
    "BFT_O_FOUR",
    "BFT_O_FOURTEEN",
    "BFT_O_NINE",
    "BFT_O_NINETEEN",
    "BFT_O_ONE",
    "BFT_O_SEVEN",
    "BFT_O_SEVENTEEN",
    "BFT_O_SIX",
    "BFT_O_T",
    "BFT_O_TEN",
    "BFT_O_THIRTY",
    "BFT_O_THIRTYSIX",
    "BFT_O_THIRTYTWO",
    "BFT_O_THREE",
    "BFT_O_TWELVE",
    "BFT_O_TWENTY",
    "BFT_O_TWENTYONE",
    "BFT_O_TWO",
    "BFT_PET_TRANSE",
    "BFT_RECORD_CAST_SKILL",
    "BFT_RELAY",
    "BFT_SEVENTY_FIVE",
    "BFT_SEVENTY_NINE",
    "BFT_SEVENTY_ONE",
    "BFT_SEVENTY_SEVEN",
    "BFT_SEVENTY_SIX",
    "BFT_SEVENTY_THREE",
    "BFT_SEVENTY_TWO",
    "BFT_SIXTY_EIGHT",
    "BFT_SIXTY_SEVEN",
    "BFT_SKILL_ACTUAL_REDUSE_COST",
    "BFT_SKILL_BAN",
    "BFT_SKILL_CHANGE",
    "BFT_SPIKES",
    "BFT_STRENGTHEN_THE_SKILL",
    "BFT_TARGET_HAS_BUFF",
)

# Mixed prefix coverage uses the same pak BuffType symbols; the prefix number
# is derived as 2000 + Enum.BuffType[symbol].
PREFIX_TYPE_SYMBOLS: tuple[str, ...] = (
    "BFT_DAMNUM_CHANGE",
    "BFT_ENTER_BATTLE",
    "BFT_KILL_BUFF",
)


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

    for symbol in BUFF_TYPE_SYMBOLS:
        order = _buff_type_value(buff_type_enum, symbol)
        primitive = buff_type_key(symbol)
        _put_unique(order_seed, order, primitive, f"buff_type={symbol!r}")
        prefix_aliases[2000 + order] = symbol

    for symbol in PREFIX_TYPE_SYMBOLS:
        prefix = 2000 + _buff_type_value(buff_type_enum, symbol)
        primitive = buff_type_key(symbol)
        _put_unique(prefix_seed, prefix, primitive, f"prefix_type={symbol!r}")
        prefix_aliases[prefix] = symbol

    raw = {
        "buff_type": {
            symbol: buff_type_key(symbol)
            for symbol in BUFF_TYPE_SYMBOLS
        },
        "prefix_type": {
            symbol: buff_type_key(symbol)
            for symbol in PREFIX_TYPE_SYMBOLS
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
