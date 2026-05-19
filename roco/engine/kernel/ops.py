"""Kernel effect dispatch — handler array indexed by registry-assigned IDs.

Handler indices are managed by handler_registry.json (see gen_prefix_map.py).
To add a new handler:
  1. Write an op_* function in the appropriate op_*.py module.
  2. Run `uv run python -m roco.compiler.gen_prefix_map` to register it.
"""

from __future__ import annotations

from roco.engine.kernel.ctx import StageCtx
from roco.engine.kernel.op_rows import ROW_TAG, ROW_TIMING, ROW_COND, condition_matches

from roco.engine.kernel.op_rows import (  # noqa: F401
    TIMING_AFTER_MOVE, TIMING_BATTLE_START, TIMING_BEFORE_MOVE,
    TIMING_CALC_DAMAGE, TIMING_CHARGE, TIMING_CHECK_HIT,
    TIMING_ENEMY_SWITCH, TIMING_FAINT, TIMING_PASSIVE_COND,
    TIMING_PASSIVE_PERSIST, TIMING_SWITCH_IN, TIMING_SWITCH_OUT,
    TIMING_TAKE_DAMAGE, TIMING_TURN_END, TIMING_TURN_START,
)

from roco.compiler.generated.handler_order import HANDLER_ORDER

import roco.engine.kernel.op_mods as _op_mods
import roco.engine.kernel.op_resources as _op_resources
import roco.engine.kernel.op_marks as _op_marks
import roco.engine.kernel.op_status as _op_status
import roco.engine.kernel.op_cute as _op_cute


def _noop(_ctx: StageCtx, _row: tuple[int, ...]) -> None:
    pass


_HANDLER_MODULES = (_op_mods, _op_resources, _op_marks, _op_status, _op_cute)


def _build_handlers() -> tuple:
    func_map: dict[str, object] = {"_noop": _noop}
    for mod in _HANDLER_MODULES:
        for name in dir(mod):
            if name.startswith("op_") and callable(getattr(mod, name)):
                func_map[name] = getattr(mod, name)
    handlers = []
    for name in HANDLER_ORDER:
        func = func_map.get(name)
        if func is None:
            raise RuntimeError(f"Handler '{name}' in registry not found in any op_* module")
        handlers.append(func)
    return tuple(handlers)


HANDLERS: tuple = _build_handlers()
HANDLER_COUNT = len(HANDLERS)
KERNEL_SUPPORTED_TAGS = tuple(range(HANDLER_COUNT))


def run_skill_timing(
    effect_rows: tuple[tuple[int, ...], ...],
    effect_range: tuple[int, int],
    timing: int,
    ctx: StageCtx,
) -> None:
    start, end = effect_range
    for idx in range(start, end):
        row = effect_rows[idx]
        if row[ROW_TIMING] == timing and condition_matches(row[ROW_COND], ctx):
            handler_idx = row[ROW_TAG]
            if 0 < handler_idx < HANDLER_COUNT:
                HANDLERS[handler_idx](ctx, row)
