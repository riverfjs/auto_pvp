"""Mark effect primitives."""

from __future__ import annotations

from roco.common.packing import MarkIdx, _set_mark, _unpack_mark
from roco.engine.kernel.ctx import StageCtx
from roco.engine.kernel.op_meta import handles_buff, handles_mark
from roco.engine.kernel.op_rows import ROW_ARG0, ROW_TARGET, TARGET_ALLY, TARGET_SELF, TARGET_TEAM
from roco.generated.mark_groups import MARK_COVER_GROUPS


def _clear_group_peers(packed: int, idx: MarkIdx) -> int:
    for group in MARK_COVER_GROUPS:
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


@handles_mark([("湿润印记", "MOISTURE")])
def op_moisture_mark(ctx: StageCtx, row: tuple[int, ...]) -> None:
    _op_mark(ctx, row, MarkIdx.MOISTURE)


@handles_mark([("龙噬印记", "DRAGON")])
def op_dragon_mark(ctx: StageCtx, row: tuple[int, ...]) -> None:
    _op_mark(ctx, row, MarkIdx.DRAGON)


@handles_mark([("蓄势印记", "MOMENTUM")])
def op_momentum_mark(ctx: StageCtx, row: tuple[int, ...]) -> None:
    _op_mark(ctx, row, MarkIdx.MOMENTUM)


@handles_mark([("风起印记", "WIND")])
def op_wind_mark(ctx: StageCtx, row: tuple[int, ...]) -> None:
    _op_mark(ctx, row, MarkIdx.WIND)


@handles_mark([("蓄电印记", "CHARGE")])
def op_charge_mark(ctx: StageCtx, row: tuple[int, ...]) -> None:
    _op_mark(ctx, row, MarkIdx.CHARGE)


@handles_mark([("光合印记", "SOLAR")])
def op_solar_mark(ctx: StageCtx, row: tuple[int, ...]) -> None:
    _op_mark(ctx, row, MarkIdx.SOLAR)


@handles_mark([("攻击印记", "ATTACK")])
def op_attack_mark(ctx: StageCtx, row: tuple[int, ...]) -> None:
    _op_mark(ctx, row, MarkIdx.ATTACK)


@handles_mark([("减速印记", "SLOW")])
def op_slow_mark(ctx: StageCtx, row: tuple[int, ...]) -> None:
    _op_mark(ctx, row, MarkIdx.SLOW)


@handles_mark([("降灵印记", "SPIRIT")])
def op_spirit_mark(ctx: StageCtx, row: tuple[int, ...]) -> None:
    _op_mark(ctx, row, MarkIdx.SPIRIT)


@handles_buff([("BFT_NINETY_FOUR", "MARK_METEOR")])
@handles_mark([("星陨印记", "METEOR")])
def op_meteor_mark(ctx: StageCtx, row: tuple[int, ...]) -> None:
    _op_mark(ctx, row, MarkIdx.METEOR)


@handles_mark([("中毒印记", "POISON")])
def op_poison_mark(ctx: StageCtx, row: tuple[int, ...]) -> None:
    _op_mark(ctx, row, MarkIdx.POISON)


@handles_mark([("棘刺印记", "THORN")])
def op_thorn_mark(ctx: StageCtx, row: tuple[int, ...]) -> None:
    _op_mark(ctx, row, MarkIdx.THORN)


def op_sluggish_mark(ctx: StageCtx, row: tuple[int, ...]) -> None:
    _op_mark(ctx, row, MarkIdx.SLUGGISH)


def op_dispel_enemy_marks(ctx: StageCtx, row: tuple[int, ...]) -> None:
    ctx.clear_enemy_marks = 1


def op_consume_marks_heal(ctx: StageCtx, row: tuple[int, ...]) -> None:
    ctx.consume_enemy_marks_heal_bps = row[ROW_ARG0]


def op_dispel_marks(ctx: StageCtx, row: tuple[int, ...]) -> None:
    """Clear marks on the targeted side.

    Pak's 1042008 ("场地转换标记") emits this op as two rows — one with
    target=self and one with target=enemy — so each row clears its own
    side and the combined skill_result clears both.  Honouring
    ``ROW_TARGET`` keeps the handler reusable for "single-side dispel"
    effects that may show up in future pak data.
    """
    if row[ROW_TARGET] in (TARGET_SELF, TARGET_ALLY, TARGET_TEAM):
        ctx.clear_self_marks = 1
    else:
        ctx.clear_enemy_marks = 1


def op_dispel_marks_to_burn(ctx: StageCtx, row: tuple[int, ...]) -> None:
    """Apply burn stacks = (marks dispelled this turn) × ``row[ROW_ARG0]``.

    Pak's 焚烧烙印 splits the work across two effect_ids: 1042008 dispels
    every mark on both sides at CALC_DAMAGE, then 1042014 fires at
    TURN_END with the per-mark multiplier 5.  By TURN_END the marks are
    already gone, so this op reads the turn's running dispel count
    handed in via ``ctx.marks_dispelled`` (snapshotted from
    ``state.marks_dispelled`` in the residual turn-end runner).
    """
    multiplier = row[ROW_ARG0]
    if multiplier <= 0 or ctx.marks_dispelled <= 0:
        return
    ctx.burn_stacks += ctx.marks_dispelled * multiplier


def op_convert_poison_to_mark(ctx: StageCtx, row: tuple[int, ...]) -> None:
    stacks = ctx.target_poison_stacks // 2
    if stacks > 0:
        ctx.mark_enemy = _mark_add(ctx.mark_enemy, MarkIdx.POISON, stacks)
