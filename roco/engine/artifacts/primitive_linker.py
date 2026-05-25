"""Link compiler primitive rows to engine runtime op names."""

from __future__ import annotations

from typing import Iterable

from roco.common.primitive_keys import (
    BATTLE_EVENT_PREFIX,
    ENGINE_HOOK_PREFIX,
    strip_prefix,
)
from roco.engine.artifacts.linked_op import LinkedOp
from roco.engine.artifacts.pak_ref_linker import link_pak_ref
from roco.engine.kernel.core.rows import TIMING_HOOK_BEFORE_MOVE
from roco.generated.pak.battle_events import BATTLE_EVENT_VALUES


PrimitiveRow = tuple[str, str, int, int, int, int, int, int]

ENGINE_HOOK_TIMINGS = {
    "before_move": TIMING_HOOK_BEFORE_MOVE,
}


def link_primitive_row(row: Iterable[object], *, source_name: str) -> LinkedOp:
    """Convert one compiler primitive row to one engine linked op."""

    rows = link_primitive_rows(row, source_name=source_name)
    if len(rows) != 1:
        raise RuntimeError(
            f"{source_name!r} produced primitive row that linked to {len(rows)} runtime rows"
        )
    return rows[0]


def link_primitive_rows(row: Iterable[object], *, source_name: str) -> tuple[LinkedOp, ...]:
    """Convert a compiler primitive row to one or more engine linked ops."""

    values = tuple(row)
    if len(values) != 8:
        raise RuntimeError(f"{source_name!r} produced malformed primitive row: {values!r}")
    primitive_raw, timing_raw, target, rate, p0, p1, p2, p3 = values
    primitive = str(primitive_raw)
    if not primitive:
        raise RuntimeError(f"{source_name!r} produced an empty effect primitive")
    timing = timing_to_kernel_value(timing_raw, source_name=source_name)
    target_i = int(target or 0)
    rate_i = int(rate or 0)
    args = (int(p0 or 0), int(p1 or 0), int(p2 or 0), int(p3 or 0))

    pak_ref = link_pak_ref(
        primitive,
        timing,
        target_i,
        rate_i,
        args[0],
        args[1],
        args[2],
        args[3],
        source_name=source_name,
    )
    if pak_ref is not None:
        return pak_ref

    raise RuntimeError(
        f"{source_name!r} produced unsupported primitive {primitive!r}; "
        "runtime catalog linking only accepts effect_ref:* or buff_ref:* rows"
    )


def timing_to_kernel_value(timing_raw: object, *, source_name: str) -> int:
    if not isinstance(timing_raw, str) or not timing_raw:
        raise RuntimeError(
            f"{source_name!r} produced non-keyed timing {timing_raw!r}; "
            "compiler rows must use battle_event:* or engine_hook:*"
        )
    battle_event = strip_prefix(timing_raw, BATTLE_EVENT_PREFIX)
    if battle_event is not None:
        value = BATTLE_EVENT_VALUES.get(battle_event)
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
