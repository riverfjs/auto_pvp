"""Mark effect primitives."""

from __future__ import annotations

from roco.common.packing import MarkIdx, _set_mark, _unpack_mark
from roco.engine.kernel.ctx import StageCtx
from roco.engine.kernel.op_rows import ROW_ARG0, ROW_TARGET, TARGET_ALLY, TARGET_SELF, TARGET_TEAM


# Marks that cover the same elemental axis and therefore replace one another
# when a new mark in the group is applied.  Currently only the wind/moisture
# pair is confirmed (风起 dispels 湿润 per skill text and the kernel test);
# extend as more pairs are validated against pak/in-game behaviour.
_MARK_COVER_GROUPS: tuple[tuple[MarkIdx, ...], ...] = (
    (MarkIdx.WIND, MarkIdx.MOISTURE),
)


def _clear_group_peers(packed: int, idx: MarkIdx) -> int:
    for group in _MARK_COVER_GROUPS:
        if idx in group:
            for other in group:
                if other != idx:
                    packed = _set_mark(packed, other, 0)
            return packed
    return packed


def _mark_add(packed: int, idx: MarkIdx, stacks: int) -> int:
    packed = _clear_group_peers(packed, idx)
    return _set_mark(packed, idx, min(15, _unpack_mark(packed, idx) + stacks))


def _op_mark(ctx: StageCtx, row: tuple[int, ...], idx: MarkIdx) -> None:
    stacks = row[ROW_ARG0]
    if stacks <= 0:
        return
    if row[ROW_TARGET] in (TARGET_SELF, TARGET_ALLY, TARGET_TEAM):
        ctx.mark_self = _mark_add(ctx.mark_self, idx, stacks)
    else:
        ctx.mark_enemy = _mark_add(ctx.mark_enemy, idx, stacks)


def op_moisture_mark(ctx: StageCtx, row: tuple[int, ...]) -> None:
    _op_mark(ctx, row, MarkIdx.MOISTURE)


def op_dragon_mark(ctx: StageCtx, row: tuple[int, ...]) -> None:
    _op_mark(ctx, row, MarkIdx.DRAGON)


def op_momentum_mark(ctx: StageCtx, row: tuple[int, ...]) -> None:
    _op_mark(ctx, row, MarkIdx.MOMENTUM)


def op_wind_mark(ctx: StageCtx, row: tuple[int, ...]) -> None:
    _op_mark(ctx, row, MarkIdx.WIND)


def op_charge_mark(ctx: StageCtx, row: tuple[int, ...]) -> None:
    _op_mark(ctx, row, MarkIdx.CHARGE)


def op_solar_mark(ctx: StageCtx, row: tuple[int, ...]) -> None:
    _op_mark(ctx, row, MarkIdx.SOLAR)


def op_attack_mark(ctx: StageCtx, row: tuple[int, ...]) -> None:
    _op_mark(ctx, row, MarkIdx.ATTACK)


def op_slow_mark(ctx: StageCtx, row: tuple[int, ...]) -> None:
    _op_mark(ctx, row, MarkIdx.SLOW)


def op_spirit_mark(ctx: StageCtx, row: tuple[int, ...]) -> None:
    _op_mark(ctx, row, MarkIdx.SPIRIT)


def op_meteor_mark(ctx: StageCtx, row: tuple[int, ...]) -> None:
    _op_mark(ctx, row, MarkIdx.METEOR)


def op_poison_mark(ctx: StageCtx, row: tuple[int, ...]) -> None:
    _op_mark(ctx, row, MarkIdx.POISON)


def op_thorn_mark(ctx: StageCtx, row: tuple[int, ...]) -> None:
    _op_mark(ctx, row, MarkIdx.THORN)


def op_sluggish_mark(ctx: StageCtx, row: tuple[int, ...]) -> None:
    _op_mark(ctx, row, MarkIdx.SLUGGISH)


def op_dispel_enemy_marks(ctx: StageCtx, row: tuple[int, ...]) -> None:
    ctx.clear_enemy_marks = 1


def op_consume_marks_heal(ctx: StageCtx, row: tuple[int, ...]) -> None:
    ctx.consume_enemy_marks_heal_bps = row[ROW_ARG0]


def op_dispel_marks(ctx: StageCtx, row: tuple[int, ...]) -> None:
    ctx.clear_self_marks = 1
    ctx.clear_enemy_marks = 1


def op_convert_poison_to_mark(ctx: StageCtx, row: tuple[int, ...]) -> None:
    stacks = ctx.target_poison_stacks // 2
    if stacks > 0:
        ctx.mark_enemy = _mark_add(ctx.mark_enemy, MarkIdx.POISON, stacks)
