"""Param-extraction helpers for pak ``effect_param`` structures.

pak stores params as ``[{"params": [v1]}, {"params": [v2, v3]}, ...]`` — these
helpers unwrap that nesting and coerce to ints, tolerating the variants pak
actually uses (scalar, single-element list, multi-element list).
"""

from __future__ import annotations

from typing import Any

from roco.generated import handler_indices as _hi
from roco.common.buffbase import pack_buff_delta_from_base_ids
from roco.generated.buffbase_params import BUFFBASE_ORDER, BUFFBASE_PARAMS

H_ANTI_HEAL = _hi.H_ANTI_HEAL
H_BURN = _hi.H_BURN
H_CUTE_BENCH_COST_REDUCE = _hi.H_CUTE_BENCH_COST_REDUCE
H_ENEMY_DEBUFF = _hi.H_ENEMY_DEBUFF
H_FREEZE = _hi.H_FREEZE
H_HIT_COUNT_BY_TEAM_SKILL_COUNT = _hi.H_HIT_COUNT_BY_TEAM_SKILL_COUNT
H_LEECH = _hi.H_LEECH
H_POISON = _hi.H_POISON
H_SELF_BUFF = _hi.H_SELF_BUFF
H_SELF_DEBUFF = _hi.H_SELF_DEBUFF

_MARK_HANDLER_NAMES = {
    "ATTACK",
    "CHARGE",
    "DRAGON",
    "METEOR",
    "MOISTURE",
    "MOMENTUM",
    "POISON",
    "SLOW",
    "SLUGGISH",
    "SOLAR",
    "SPIRIT",
    "THORN",
    "WIND",
}
_MARK_HANDLER_IDS = frozenset(
    value
    for name, value in vars(_hi).items()
    if name.endswith("_MARK")
    and name.removeprefix("H_").removesuffix("_MARK") in _MARK_HANDLER_NAMES
)


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


def is_status_or_mark_handler(h: int) -> bool:
    """True if handler ``h`` packs a stack count in p0."""
    return h in (H_BURN, H_POISON, H_FREEZE, H_LEECH) or h in _MARK_HANDLER_IDS


def pack_handler_params(
    h: int,
    buff_id: int,
    buff_conf: dict[int, dict],
    stack_count: int = 1,
) -> tuple[int, int, int, int]:
    """Pack kernel-compatible params for handler ``h`` from a pak buff record.

    Each kernel handler reads specific semantics from p0-p3, so the packing
    rule depends on the handler family:

    * status / mark handlers carry ``stack_count`` in p0;
    * stat-buff handlers pack up to four ``buff_base_ids`` across p0-p3;
    * unknown handlers fall back to the same stat-buff packing.
    """
    rec = buff_conf.get(buff_id) or {}
    base_ids = [bid for bid in (rec.get("buff_base_ids") or []) if bid]

    if is_status_or_mark_handler(h):
        return (max(1, stack_count), 0, 0, 0)
    if h == H_HIT_COUNT_BY_TEAM_SKILL_COUNT:
        return (max(1, stack_count), 0, 0, 0)
    if h == H_ANTI_HEAL:
        multiplier = 2
        if base_ids:
            base_params = BUFFBASE_PARAMS.get(int(base_ids[0])) or ()
            trigger = base_params[3] if len(base_params) > 3 else ()
            if isinstance(trigger, tuple) and len(trigger) >= 2:
                multiplier = max(1, int(trigger[1]) // 10)
        return (multiplier, 0, 0, 0)
    if h == H_CUTE_BENCH_COST_REDUCE:
        amount = _cute_bench_cost_reduce_amount(base_ids, buff_conf)
        if amount <= 0:
            raise RuntimeError(f"cannot derive cute bench cost reduction from buff {buff_id}")
        return (amount, 0, 0, 0)
    if h in (H_SELF_BUFF, H_ENEMY_DEBUFF, H_SELF_DEBUFF):
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
