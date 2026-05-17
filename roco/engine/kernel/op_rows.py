"""Effect row layout and timing constants for the fixed kernel."""

from __future__ import annotations

from roco.engine.kernel.ctx import StageCtx

ROW_TAG = 0
ROW_TIMING = 1
ROW_TARGET = 2
ROW_FLAGS = 3
ROW_COND = 4
ROW_ARG0 = 5
ROW_ARG1 = 6
ROW_ARG2 = 7
ROW_ARG3 = 8

COND_NONE = 0
COND_COUNTER = 1
COND_COUNTER_STATUS = 2
COND_NOT_BLOCKED = 3

TARGET_SELF = 1
TARGET_ALLY = 3
TARGET_TEAM = 4

TIMING_CALC_DAMAGE = 13
TIMING_TURN_START = 2
TIMING_BEFORE_MOVE = 3
TIMING_AFTER_MOVE = 5
TIMING_TURN_END = 6
TIMING_SWITCH_IN = 7
TIMING_SWITCH_OUT = 8
TIMING_TAKE_DAMAGE = 16
TIMING_ENEMY_SWITCH = 17


def condition_matches(cond: int, ctx: StageCtx) -> bool:
    if cond in (COND_NONE, COND_NOT_BLOCKED):
        return True
    if cond == COND_COUNTER:
        return bool(ctx.counter_success)
    if cond == COND_COUNTER_STATUS:
        return bool(ctx.counter_success and ctx.counter_category == 2)
    return False
