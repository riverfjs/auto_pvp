"""Mark-domain runtime helpers and ops."""

from __future__ import annotations

from roco.common.enums import StatusType
from roco.common.packing import MarkIdx, _set_mark, _unpack_mark
from roco.engine.kernel.core.ctx import StageCtx
from roco.engine.kernel.core.rows import ROW_ARG0, ROW_TARGET, TARGET_ALLY, TARGET_SELF, TARGET_TEAM
from roco.generated.pak.mark_groups import MARK_COVER_GROUPS


def mark_idx_for_status(status: StatusType) -> MarkIdx:
    if status == StatusType.POISON:
        return MarkIdx.POISON
    raise RuntimeError(f"status {status!r} has no mark conversion")


def add_mark_delta(packed: int, status: StatusType, stacks: int) -> int:
    return _mark_add(packed, mark_idx_for_status(status), stacks)


def op_meteor_mark_by_target_mark_total(ctx: StageCtx, row: tuple[int, ...]) -> None:
    stacks = ctx.target_mark_total * max(1, row[ROW_ARG0])
    if stacks <= 0:
        return
    if row[ROW_TARGET] in (TARGET_SELF, TARGET_ALLY, TARGET_TEAM):
        ctx.mark_self = _mark_add(ctx.mark_self, MarkIdx.METEOR, stacks)
    else:
        ctx.mark_enemy = _mark_add(ctx.mark_enemy, MarkIdx.METEOR, stacks)


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
