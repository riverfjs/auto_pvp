"""Kernel effect dispatch — HANDLERS comes from generated/handler_table.

Handler indices are engine-owned runtime artifacts.  To add a new handler:
  1. Write an op_* function in the appropriate op_*.py module.
  2. Run `uv run python -m roco.engine.kernel.gen_runtime_artifacts`.
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

from roco.generated.handler_table import HANDLERS, HANDLER_COUNT

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
