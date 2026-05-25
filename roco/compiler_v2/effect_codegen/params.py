"""Param-extraction helpers for pak ``effect_param`` structures.

pak stores params as ``[{"params": [v1]}, {"params": [v2, v3]}, ...]`` — these
helpers unwrap that nesting and coerce to ints, tolerating the variants pak
actually uses (scalar, single-element list, multi-element list).
"""

from __future__ import annotations

from typing import Any

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
