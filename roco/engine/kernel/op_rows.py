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

TIMING_CALC_DAMAGE = 6
TIMING_CHECK_HIT = 7
TIMING_FAINT = 9
TIMING_TURN_START = 10
TIMING_AFTER_MOVE = 11
TIMING_TURN_END = 12
TIMING_PASSIVE_PERSIST = 23
TIMING_SWITCH_IN = 24
TIMING_CHARGE = 25
TIMING_PASSIVE_COND = 26
TIMING_BATTLE_START = 27
TIMING_BEFORE_MOVE = 901
TIMING_TAKE_DAMAGE = 902
TIMING_SWITCH_OUT = 903
TIMING_ENEMY_SWITCH = 904


def condition_matches(cond: int, ctx: StageCtx) -> bool:
    if cond in (COND_NONE, COND_NOT_BLOCKED):
        return True
    if cond == COND_COUNTER:
        return bool(ctx.counter_success)
    if cond == COND_COUNTER_STATUS:
        return bool(ctx.counter_success and ctx.counter_category == 2)
    return False
