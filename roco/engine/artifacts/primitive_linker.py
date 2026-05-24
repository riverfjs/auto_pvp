"""Link compiler primitive rows to engine runtime rows."""

from __future__ import annotations

from typing import Iterable

from roco.common.primitive_keys import (
    BATTLE_EVENT_PREFIX,
    ENGINE_HOOK_PREFIX,
    strip_prefix,
)
from roco.engine.artifacts.primitive_bindings import handler_const_from_primitive
from roco.engine.kernel.op_rows import TIMING_BEFORE_MOVE
from roco.generated import handler_indices as hi
from roco.generated.static.lua_enums import LUA_ENUMS


PrimitiveRow = tuple[str, str, int, int, int, int, int, int]
RuntimeEffectRow = tuple[int, int, int, int, int, int, int, int]

ENGINE_HOOK_TIMINGS = {
    "before_move": TIMING_BEFORE_MOVE,
}


def primitive_to_handler_idx(primitive: str) -> int:
    """Resolve a primitive string to the current generated handler index."""

    const = handler_const_from_primitive(primitive)
    try:
        value = getattr(hi, const)
    except AttributeError as exc:
        raise RuntimeError(
            f"primitive {primitive!r} resolves to missing engine handler {const!r}"
        ) from exc
    if value <= 0:
        raise RuntimeError(f"primitive {primitive!r} resolved to invalid handler index {value}")
    return int(value)


def link_primitive_row(row: Iterable[object], *, source_name: str) -> RuntimeEffectRow:
    """Convert a compiler primitive row to an engine runtime effect row."""

    values = tuple(row)
    if len(values) != 8:
        raise RuntimeError(f"{source_name!r} produced malformed primitive row: {values!r}")
    primitive_raw, timing_raw, target, rate, p0, p1, p2, p3 = values
    primitive = str(primitive_raw)
    if not primitive:
        raise RuntimeError(f"{source_name!r} produced an empty effect primitive")
    return (
        primitive_to_handler_idx(primitive),
        timing_to_kernel_value(timing_raw, source_name=source_name),
        int(target or 0),
        int(rate or 0),
        int(p0 or 0),
        int(p1 or 0),
        int(p2 or 0),
        int(p3 or 0),
    )


def timing_to_kernel_value(timing_raw: object, *, source_name: str) -> int:
    if not isinstance(timing_raw, str) or not timing_raw:
        raise RuntimeError(
            f"{source_name!r} produced non-keyed timing {timing_raw!r}; "
            "compiler rows must use battle_event:* or engine_hook:*"
        )
    battle_event = strip_prefix(timing_raw, BATTLE_EVENT_PREFIX)
    if battle_event is not None:
        value = LUA_ENUMS.get("BattleEvent", {}).get(battle_event)
        if value is None:
            raise RuntimeError(
                f"{source_name!r} produced unknown pak battle event timing {timing_raw!r}"
            )
        return int(value)
    engine_hook = strip_prefix(timing_raw, ENGINE_HOOK_PREFIX)
    if engine_hook is not None:
        value = ENGINE_HOOK_TIMINGS.get(engine_hook)
        if value is None:
            raise RuntimeError(
                f"{source_name!r} produced unknown engine timing hook {timing_raw!r}"
            )
        return int(value)
    raise RuntimeError(
        f"{source_name!r} produced unsupported timing key {timing_raw!r}; "
        "expected battle_event:* or engine_hook:*"
    )
