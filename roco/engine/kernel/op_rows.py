"""Effect row layout and timing constants for the fixed kernel."""

from __future__ import annotations

from roco.engine.kernel.ctx import StageCtx
from roco.generated import battle_events as _battle_events

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
TARGET_ENEMY = 2
TARGET_ALLY = 3
TARGET_TEAM = 4

TIMING_PAK_ROUND_CALC_START = _battle_events.BEVT_ROUND_CALC_START
TIMING_PAK_ROUND_END = _battle_events.BEVT_ROUND_END
TIMING_PAK_BEFORE_SDT_ADD_ENERGY = _battle_events.BEVT_BEFORE_SDT_ADD_ENERGY
TIMING_PAK_BEFORE_SKILL_DAMAGE_CALC = _battle_events.BEVT_BEFORE_SKILL_DAMAGE_CALC
TIMING_PAK_BEFORE_HURT = _battle_events.BEVT_BEFORE_HURT
TIMING_PAK_BEFORE_ADD = _battle_events.BEVT_BEFORE_ADD
TIMING_PAK_AFTER_HURT = _battle_events.BEVT_AFTER_HURT
TIMING_PAK_SDT = _battle_events.BEVT_SDT
TIMING_PAK_COUNTER_FINISH = _battle_events.BEVT_COUNTER_FINISH
TIMING_PAK_BEFORE_DIE = _battle_events.BEVT_BEFORE_DIE
TIMING_PAK_HP_CHANGED = _battle_events.BEVT_HP_CHANGED

TIMING_HOOK_BEFORE_MOVE = 901
TIMING_HOOK_TAKE_DAMAGE = 902
TIMING_HOOK_SWITCH_OUT = 903
TIMING_HOOK_ENEMY_SWITCH = 904


def condition_matches(cond: int, ctx: StageCtx) -> bool:
    if cond in (COND_NONE, COND_NOT_BLOCKED):
        return True
    if cond == COND_COUNTER:
        return bool(ctx.counter_success)
    if cond == COND_COUNTER_STATUS:
        return bool(ctx.counter_success and ctx.counter_category == 2)
    return False
