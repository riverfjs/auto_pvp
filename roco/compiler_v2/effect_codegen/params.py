"""Param-extraction helpers for pak ``effect_param`` structures.

pak stores params as ``[{"params": [v1]}, {"params": [v2, v3]}, ...]`` — these
helpers unwrap that nesting and coerce to ints, tolerating the variants pak
actually uses (scalar, single-element list, multi-element list).
"""

from __future__ import annotations

from typing import Any

from roco.common.primitive_keys import (
    BUFF_REF_PREFIX,
    buff_type_key,
    effect_order_key,
)
from roco.compiler_v2.effect_codegen.buffbase_source import (
    pack_buff_delta_from_base_ids,
)

_STATUS_OR_MARK_BUFF_TYPES = frozenset({
    buff_type_key("BFT_ABSORB"),
    buff_type_key("BFT_DAM"),
    buff_type_key("BFT_FREEZE"),
    buff_type_key("BFT_NINETY_FOUR"),
    buff_type_key("BFT_SIXTY_EIGHT"),
})

_STAT_DELTA_BUFF_TYPES = frozenset(
    buff_type_key(symbol)
    for symbol in (
        "BFT_ASSIGN_ATTACK_FIRST",
        "BFT_ATTR_CHANGE",
        "BFT_BAN",
        "BFT_BUFF_AFTER_SKILL",
        "BFT_CAST_REPEAT_SKILL",
        "BFT_CAST_SKILL_AFTER_ATTACK",
        "BFT_CHANGE_CATCH_VALUE",
        "BFT_CHECK_HP",
        "BFT_DETECT_ENEMY_SKILLS",
        "BFT_EIGHTY",
        "BFT_EIGHTY_EIGHT",
        "BFT_EIGHTY_FOUR",
        "BFT_EIGHTY_NINE",
        "BFT_EIGHTY_SIX",
        "BFT_EIGHTY_THREE",
        "BFT_ENTER_BATTLE",
        "BFT_FIELD_REDUSE_COST",
        "BFT_INC_DAM_BY_BUFF",
        "BFT_KILL_BUFF",
        "BFT_NINETY_THREE",
        "BFT_NINETY_TWO",
        "BFT_O_EIGHTEEN",
        "BFT_O_ELEVEN",
        "BFT_O_FIVE",
        "BFT_O_FORTYTWO",
        "BFT_O_FOUR",
        "BFT_O_FOURTEEN",
        "BFT_O_NINETEEN",
        "BFT_O_ONE",
        "BFT_O_SEVENTEEN",
        "BFT_O_SIX",
        "BFT_O_TEN",
        "BFT_O_THIRTY",
        "BFT_O_THIRTYSIX",
        "BFT_O_THIRTYTWO",
        "BFT_O_THREE",
        "BFT_O_TWELVE",
        "BFT_O_TWENTY",
        "BFT_O_TWENTYONE",
        "BFT_RECORD_CAST_SKILL",
        "BFT_RELAY",
        "BFT_SEVENTY_FIVE",
        "BFT_SEVENTY_NINE",
        "BFT_SEVENTY_SEVEN",
        "BFT_SEVENTY_SIX",
        "BFT_SEVENTY_THREE",
        "BFT_SEVENTY_TWO",
        "BFT_SIXTY_SEVEN",
        "BFT_SKILL_BAN",
        "BFT_SKILL_CHANGE",
        "BFT_SPIKES",
        "BFT_STRENGTHEN_THE_SKILL",
        "BFT_TARGET_HAS_BUFF",
    )
)

_ET_MULTIPLE = effect_order_key("ET_MULTIPLE")


def unwrap_param(lst: list, index: int) -> Any:
    """Extract the raw value at ``lst[index]``.

    Returns the scalar element if the wrapped ``params`` list has length 1,
    the whole list when longer, or ``None`` when the slot is missing/empty.
    """
    if index >= len(lst):
        return None
    item = lst[index]
    if isinstance(item, dict):
        inner = item.get("params", [])
        if isinstance(inner, list) and inner:
            return inner[0] if len(inner) == 1 else inner
        return None
    return item


def safe_int(lst: list, index: int, default: int = 0) -> int:
    """Coerce ``lst[index]`` to an int, returning ``default`` on failure."""
    val = unwrap_param(lst, index)
    if val is None:
        return default
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def extract_int_list(lst: list, index: int) -> list[int]:
    """Return ``lst[index]`` as a list of non-zero ints (scalar or list)."""
    val = unwrap_param(lst, index)
    if val is None:
        return []
    if isinstance(val, list):
        return [int(v) for v in val if v]
    if isinstance(val, (int, float)) and val:
        return [int(val)]
    return []


def is_status_or_mark_primitive(primitive: str) -> bool:
    """True if primitive ``primitive`` packs a stack count in p0."""
    return (
        primitive.startswith(BUFF_REF_PREFIX)
        or primitive in _STATUS_OR_MARK_BUFF_TYPES
    )


def is_flat_hit_count_delta_primitive(primitive: str) -> bool:
    return primitive == _ET_MULTIPLE


def pack_primitive_params(
    primitive: str,
    buff_id: int,
    buff_conf: dict[int, dict],
    stack_count: int = 1,
) -> tuple[int, int, int, int]:
    """Pack primitive params from a pak buff record.

    Each primitive reads specific semantics from p0-p3, so the packing rule
    depends on the primitive family:

    * status / mark primitives carry ``stack_count`` in p0;
    * stat-buff primitives pack a packed stat delta in p0;
    * unknown primitives fall back to raw ``buff_base_ids`` across p0-p3.
    """
    rec = buff_conf.get(buff_id) or {}
    base_ids = [bid for bid in (rec.get("buff_base_ids") or []) if bid]

    if is_status_or_mark_primitive(primitive):
        return (max(1, stack_count), 0, 0, 0)
    if primitive in _STAT_DELTA_BUFF_TYPES:
        return (pack_buff_delta_from_base_ids(tuple(int(v) for v in base_ids)), 0, 0, 0)
    p = (base_ids + [0, 0, 0, 0])[:4]
    return (p[0], p[1], p[2], p[3])
