"""Kernel effect dispatch — HANDLERS comes from generated/runtime/handler_table.

Handler indices are engine-owned runtime artifacts.  To add a new handler:
  1. Write an op_* function in the appropriate op_*.py module.
  2. Run `uv run python -m roco.engine.kernel.generation.gen_runtime_artifacts`.
"""

from __future__ import annotations

from roco.engine.kernel.core.ctx import StageCtx
from roco.engine.kernel.core.rows import ROW_HANDLER_IDX, ROW_TIMING, ROW_COND, condition_matches

from roco.engine.kernel.core.rows import (  # noqa: F401
    TIMING_PAK_BEFORE_HURT, TIMING_PAK_HP_CHANGED, TIMING_HOOK_BEFORE_MOVE,
    TIMING_PAK_ROUND_CALC_START, TIMING_PAK_COUNTER_FINISH, TIMING_PAK_ROUND_END,
    TIMING_HOOK_ENEMY_SWITCH, TIMING_PAK_BEFORE_SDT_ADD_ENERGY, TIMING_PAK_BEFORE_DIE,
    TIMING_PAK_AFTER_HURT, TIMING_PAK_SDT, TIMING_HOOK_SWITCH_OUT,
    TIMING_HOOK_TAKE_DAMAGE, TIMING_PAK_BEFORE_ADD, TIMING_PAK_BEFORE_SKILL_DAMAGE_CALC,
)

from roco.generated.runtime.handler_table import HANDLERS, HANDLER_COUNT

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
            handler_idx = row[ROW_HANDLER_IDX]
            if 0 < handler_idx < HANDLER_COUNT:
                HANDLERS[handler_idx](ctx, row)
