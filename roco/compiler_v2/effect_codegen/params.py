"""Param-extraction helpers for pak ``effect_param`` structures.

pak stores params as ``[{"params": [v1]}, {"params": [v2, v3]}, ...]`` — these
helpers unwrap that nesting and coerce to ints, tolerating the variants pak
actually uses (scalar, single-element list, multi-element list).
"""

from __future__ import annotations

from typing import Any

from roco.common.primitive_keys import (
    MARK_NOTE_PREFIX,
    STATUS_NOTE_PREFIX,
    buff_type_key,
    effect_order_key,
    struct_key,
)
from roco.compiler_v2.effect_codegen.buffbase_source import (
    BUFFBASE_ORDER,
    BUFFBASE_PARAMS,
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

_TEAM_SKILL_HIT_COUNT = struct_key("team_skill_hit_count")
_FLAT_HIT_COUNT_DELTA = struct_key("flat_hit_count_delta")
_HIT_COUNT_PERCENT_DELTA = struct_key("hit_count_percent_delta")
_HEAL_REVERSAL = struct_key("heal_reversal")
_CUTE_BENCH_COST_REDUCE = struct_key("cute_bench_cost_reduce")
_ACTIVE_IMMUNITY_BUFF = struct_key("active_immunity_buff")
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
        primitive.startswith(MARK_NOTE_PREFIX)
        or primitive.startswith(STATUS_NOTE_PREFIX)
        or primitive in _STATUS_OR_MARK_BUFF_TYPES
    )


def is_flat_hit_count_delta_primitive(primitive: str) -> bool:
    return primitive in (_FLAT_HIT_COUNT_DELTA, _ET_MULTIPLE)


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
    if primitive == _TEAM_SKILL_HIT_COUNT:
        return (max(1, stack_count), 0, 0, 0)
    if primitive == _FLAT_HIT_COUNT_DELTA:
        delta, skill_ids = _flat_hit_count_delta(base_ids)
        if delta == 0:
            raise RuntimeError(f"cannot derive flat hit-count delta from buff {buff_id}")
        padded = (skill_ids + (0, 0, 0))[:3]
        return (delta, padded[0], padded[1], padded[2])
    if primitive == _HIT_COUNT_PERCENT_DELTA:
        amount = _hit_count_percent_delta_amount(base_ids)
        if amount == 0:
            raise RuntimeError(f"cannot derive percent hit-count delta from buff {buff_id}")
        return (amount, 0, 0, 0)
    if primitive == _HEAL_REVERSAL:
        multiplier = 2
        if base_ids:
            base_params = BUFFBASE_PARAMS.get(int(base_ids[0])) or ()
            trigger = base_params[3] if len(base_params) > 3 else ()
            if isinstance(trigger, tuple) and len(trigger) >= 2:
                multiplier = max(1, int(trigger[1]) // 10)
        return (multiplier, 0, 0, 0)
    if primitive == _CUTE_BENCH_COST_REDUCE:
        amount = _cute_bench_cost_reduce_amount(base_ids, buff_conf)
        if amount <= 0:
            raise RuntimeError(f"cannot derive cute bench cost reduction from buff {buff_id}")
        return (amount, 0, 0, 0)
    if primitive == _ACTIVE_IMMUNITY_BUFF:
        reduce_type, reduce_param0, reduce_param1 = _single_reduce_rule(buff_id, buff_conf)
        return (buff_id, reduce_type, reduce_param0, reduce_param1)
    if primitive in _STAT_DELTA_BUFF_TYPES:
        return (pack_buff_delta_from_base_ids(tuple(int(v) for v in base_ids)), 0, 0, 0)
    p = (base_ids + [0, 0, 0, 0])[:4]
    return (p[0], p[1], p[2], p[3])


def _as_int_tuple(value: Any) -> tuple[int, ...]:
    if isinstance(value, tuple):
        return tuple(int(v) for v in value)
    if isinstance(value, list):
        return tuple(int(v) for v in value)
    if value is None:
        return ()
    return (int(value),)


def _single_int(value: Any) -> int | None:
    values = _as_int_tuple(value)
    return values[0] if len(values) == 1 else None


def _flat_hit_count_delta(base_ids: list[int]) -> tuple[int, tuple[int, ...]]:
    if len(base_ids) != 1:
        return 0, ()
    base_id = int(base_ids[0])
    if BUFFBASE_ORDER.get(base_id) != 45:
        return 0, ()
    base_params = BUFFBASE_PARAMS.get(base_id) or ()
    if len(base_params) < 3:
        return 0, ()
    delta = _single_int(base_params[0])
    mode = _single_int(base_params[2])
    if delta is None or delta == 0 or mode != 0:
        return 0, ()
    skill_ids = tuple(v for v in _as_int_tuple(base_params[1]) if v > 0)
    if len(skill_ids) > 3:
        return 0, ()
    return delta, skill_ids


def _hit_count_percent_delta_amount(base_ids: list[int]) -> int:
    if len(base_ids) != 1:
        return 0
    base_id = int(base_ids[0])
    if BUFFBASE_ORDER.get(base_id) != 45:
        return 0
    base_params = BUFFBASE_PARAMS.get(base_id) or ()
    if len(base_params) < 3:
        return 0
    amount = _single_int(base_params[0])
    mode = _single_int(base_params[2])
    if amount is None or amount == 0 or mode != 1:
        return 0
    return amount


def _cute_bench_cost_reduce_amount(base_ids: list[int], buff_conf: dict[int, dict]) -> int:
    for raw_base_id in base_ids:
        base_id = int(raw_base_id)
        if BUFFBASE_ORDER.get(base_id) != 40:
            continue
        base_params = BUFFBASE_PARAMS.get(base_id) or ()
        if len(base_params) < 3:
            continue
        target_buff_id = _single_int(base_params[2])
        if target_buff_id is None:
            continue
        target = buff_conf.get(target_buff_id) or {}
        target_base_ids = [int(v) for v in target.get("buff_base_ids") or () if v]
        if len(target_base_ids) != 1:
            continue
        target_base_id = target_base_ids[0]
        if BUFFBASE_ORDER.get(target_base_id) != 32:
            continue
        target_params = BUFFBASE_PARAMS.get(target_base_id) or ()
        if len(target_params) < 4 or _as_int_tuple(target_params[0]) != (0,):
            continue
        cost_delta = _single_int(target_params[3])
        if cost_delta is not None and cost_delta < 0:
            return abs(cost_delta)
    return 0


def _single_reduce_rule(buff_id: int, buff_conf: dict[int, dict]) -> tuple[int, int, int]:
    rec = buff_conf.get(buff_id) or {}
    rules = rec.get("buff_group_reduce") or []
    if len(rules) != 1 or not isinstance(rules[0], dict):
        raise RuntimeError(f"active immunity buff {buff_id} must have one pak reduce rule")
    rule = rules[0]
    reduce_type = int(rule.get("reduce_type") or 0)
    params = rule.get("reduce_param") or []
    if not isinstance(params, list):
        params = []
    p0 = int(params[0]) if len(params) > 0 else 0
    p1 = int(params[1]) if len(params) > 1 else 0
    return reduce_type, p0, p1
