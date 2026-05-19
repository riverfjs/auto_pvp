"""Param-extraction helpers for pak ``effect_param`` structures.

pak stores params as ``[{"params": [v1]}, {"params": [v2, v3]}, ...]`` — these
helpers unwrap that nesting and coerce to ints, tolerating the variants pak
actually uses (scalar, single-element list, multi-element list).
"""

from __future__ import annotations

from typing import Any

from roco.generated.handler_indices import (
    H_BURN,
    H_ENEMY_DEBUFF,
    H_FREEZE,
    H_LEECH,
    H_MOMENTUM_MARK,
    H_POISON,
    H_POISON_MARK,
    H_SELF_BUFF,
    H_SELF_DEBUFF,
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
    return (
        h in (H_BURN, H_POISON, H_FREEZE, H_LEECH)
        or H_POISON_MARK <= h <= H_MOMENTUM_MARK
    )


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
    if h in (H_SELF_BUFF, H_ENEMY_DEBUFF, H_SELF_DEBUFF):
        p = (base_ids + [0, 0, 0, 0])[:4]
        return (p[0], p[1], p[2], p[3])
    p = (base_ids + [0, 0, 0, 0])[:4]
    return (p[0], p[1], p[2], p[3])
