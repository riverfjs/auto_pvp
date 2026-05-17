"""Fixed-kernel effect op table over integer effect rows."""

from __future__ import annotations

from roco.engine.common.packing import MarkIdx, _set_mark, _unpack_mark
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
TARGET_SELF = 1
TARGET_ALLY = 3
TARGET_TEAM = 4
TAG_DAMAGE = 1
TAG_HEAL_HP = 2
TAG_HEAL_ENERGY = 3
TAG_BURN = 9
TAG_POISON = 10
TAG_FREEZE = 11
TAG_LEECH = 12
TAG_DAMAGE_REDUCTION = 14
TAG_WEATHER = 17
TAG_POISON_MARK = 27
TAG_MOISTURE_MARK = 28
TAG_DRAGON_MARK = 29
TAG_WIND_MARK = 30
TAG_CHARGE_MARK = 31
TAG_SOLAR_MARK = 32
TAG_ATTACK_MARK = 33
TAG_SLOW_MARK = 34
TAG_SLUGGISH_MARK = 35
TAG_SPIRIT_MARK = 36
TAG_METEOR_MARK = 37
TAG_THORN_MARK = 38
TAG_MOMENTUM_MARK = 39
TAG_DISPEL_ENEMY_MARKS = 40
TAG_DISPEL_MARKS = 63
MAX_TAG = 146
TIMING_CALC_DAMAGE = 13
TIMING_AFTER_MOVE = 5


def _op_unsupported(ctx: StageCtx, row: tuple[int, ...]) -> None:
    raise NotImplementedError(row[ROW_TAG])


def _op_damage(ctx: StageCtx, row: tuple[int, ...]) -> None:
    if row[ROW_ARG0] > 0:
        ctx.power = row[ROW_ARG0]
    if row[ROW_ARG1] > 0:
        ctx.hit_count = row[ROW_ARG1]


def _noop(ctx: StageCtx, row: tuple[int, ...]) -> None:
    return


def _op_burn(ctx: StageCtx, row: tuple[int, ...]) -> None:
    ctx.burn_stacks += row[ROW_ARG0]


def _op_poison(ctx: StageCtx, row: tuple[int, ...]) -> None:
    ctx.poison_stacks += row[ROW_ARG0]


def _op_freeze(ctx: StageCtx, row: tuple[int, ...]) -> None:
    ctx.freeze_stacks += row[ROW_ARG0]


def _op_leech(ctx: StageCtx, row: tuple[int, ...]) -> None:
    ctx.leech_stacks += row[ROW_ARG0]


def _op_weather(ctx: StageCtx, row: tuple[int, ...]) -> None:
    ctx.weather = row[ROW_ARG0]
    ctx.weather_turns = row[ROW_ARG1]


def _mark_add(packed: int, idx: MarkIdx, stacks: int) -> int:
    return _set_mark(packed, idx, min(15, _unpack_mark(packed, idx) + stacks))


def _op_mark(ctx: StageCtx, row: tuple[int, ...], idx: MarkIdx) -> None:
    stacks = row[ROW_ARG0]
    if stacks <= 0:
        return
    if row[ROW_TARGET] in (TARGET_SELF, TARGET_ALLY, TARGET_TEAM):
        ctx.mark_self = _mark_add(ctx.mark_self, idx, stacks)
    else:
        ctx.mark_enemy = _mark_add(ctx.mark_enemy, idx, stacks)


def _op_moisture_mark(ctx: StageCtx, row: tuple[int, ...]) -> None:
    _op_mark(ctx, row, MarkIdx.MOISTURE)


def _op_dragon_mark(ctx: StageCtx, row: tuple[int, ...]) -> None:
    _op_mark(ctx, row, MarkIdx.DRAGON)


def _op_momentum_mark(ctx: StageCtx, row: tuple[int, ...]) -> None:
    _op_mark(ctx, row, MarkIdx.MOMENTUM)


def _op_wind_mark(ctx: StageCtx, row: tuple[int, ...]) -> None:
    _op_mark(ctx, row, MarkIdx.WIND)


def _op_charge_mark(ctx: StageCtx, row: tuple[int, ...]) -> None:
    _op_mark(ctx, row, MarkIdx.CHARGE)


def _op_solar_mark(ctx: StageCtx, row: tuple[int, ...]) -> None:
    _op_mark(ctx, row, MarkIdx.SOLAR)


def _op_attack_mark(ctx: StageCtx, row: tuple[int, ...]) -> None:
    _op_mark(ctx, row, MarkIdx.ATTACK)


def _op_slow_mark(ctx: StageCtx, row: tuple[int, ...]) -> None:
    _op_mark(ctx, row, MarkIdx.SLOW)


def _op_spirit_mark(ctx: StageCtx, row: tuple[int, ...]) -> None:
    _op_mark(ctx, row, MarkIdx.SPIRIT)


def _op_meteor_mark(ctx: StageCtx, row: tuple[int, ...]) -> None:
    _op_mark(ctx, row, MarkIdx.METEOR)


def _op_poison_mark(ctx: StageCtx, row: tuple[int, ...]) -> None:
    _op_mark(ctx, row, MarkIdx.POISON)


def _op_thorn_mark(ctx: StageCtx, row: tuple[int, ...]) -> None:
    _op_mark(ctx, row, MarkIdx.THORN)


def _op_sluggish_mark(ctx: StageCtx, row: tuple[int, ...]) -> None:
    _op_mark(ctx, row, MarkIdx.SLUGGISH)


def _op_dispel_enemy_marks(ctx: StageCtx, row: tuple[int, ...]) -> None:
    ctx.clear_enemy_marks = 1


def _op_dispel_marks(ctx: StageCtx, row: tuple[int, ...]) -> None:
    ctx.clear_self_marks = 1
    ctx.clear_enemy_marks = 1


_TABLE = [_op_unsupported] * (MAX_TAG + 1)
_TABLE[TAG_DAMAGE] = _op_damage
_TABLE[TAG_DAMAGE_REDUCTION] = _noop
_TABLE[TAG_HEAL_HP] = _noop
_TABLE[TAG_HEAL_ENERGY] = _noop
_TABLE[TAG_BURN] = _op_burn
_TABLE[TAG_POISON] = _op_poison
_TABLE[TAG_FREEZE] = _op_freeze
_TABLE[TAG_LEECH] = _op_leech
_TABLE[TAG_WEATHER] = _op_weather
_TABLE[TAG_MOISTURE_MARK] = _op_moisture_mark
_TABLE[TAG_DRAGON_MARK] = _op_dragon_mark
_TABLE[TAG_MOMENTUM_MARK] = _op_momentum_mark
_TABLE[TAG_WIND_MARK] = _op_wind_mark
_TABLE[TAG_CHARGE_MARK] = _op_charge_mark
_TABLE[TAG_SOLAR_MARK] = _op_solar_mark
_TABLE[TAG_ATTACK_MARK] = _op_attack_mark
_TABLE[TAG_SLOW_MARK] = _op_slow_mark
_TABLE[TAG_SPIRIT_MARK] = _op_spirit_mark
_TABLE[TAG_METEOR_MARK] = _op_meteor_mark
_TABLE[TAG_POISON_MARK] = _op_poison_mark
_TABLE[TAG_THORN_MARK] = _op_thorn_mark
_TABLE[TAG_SLUGGISH_MARK] = _op_sluggish_mark
_TABLE[TAG_DISPEL_ENEMY_MARKS] = _op_dispel_enemy_marks
_TABLE[TAG_DISPEL_MARKS] = _op_dispel_marks
OP_TABLE = tuple(_TABLE)
KERNEL_SUPPORTED_TAGS = tuple(
    idx for idx, op in enumerate(OP_TABLE)
    if op is not _op_unsupported
)


def run_skill_timing(effect_rows: tuple[tuple[int, ...], ...], effect_range: tuple[int, int], timing: int, ctx: StageCtx) -> None:
    start, end = effect_range
    for idx in range(start, end):
        row = effect_rows[idx]
        if row[ROW_TIMING] == timing and row[ROW_COND] == COND_NONE:
            OP_TABLE[row[ROW_TAG]](ctx, row)
