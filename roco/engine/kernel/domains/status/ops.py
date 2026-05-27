"""Status-domain runtime ops."""

from __future__ import annotations

from roco.common.enums import StatusType
from roco.engine.kernel.core.ctx import StageCtx
from roco.engine.kernel.core.rows import ROW_ARG0, ROW_ARG1, ROW_TARGET, TARGET_ALLY, TARGET_SELF, TARGET_TEAM


def op_convert_poison_status_to_mark(ctx: StageCtx, row: tuple[int, ...]) -> None:
    required = max(1, row[ROW_ARG0])
    produced = max(0, row[ROW_ARG1])
    if produced <= 0:
        return
    if row[ROW_TARGET] in (TARGET_SELF, TARGET_ALLY, TARGET_TEAM):
        conversions = ctx.actor_poison_stacks // required
        if conversions <= 0:
            return
        ctx.self_poison_consume += conversions * required
        from roco.engine.kernel.domains.mark.ops import add_mark_delta
        ctx.mark_self = add_mark_delta(ctx.mark_self, StatusType.POISON, conversions * produced)
    else:
        conversions = ctx.target_poison_stacks // required
        if conversions <= 0:
            return
        ctx.enemy_poison_consume += conversions * required
        from roco.engine.kernel.domains.mark.ops import add_mark_delta
        ctx.mark_enemy = add_mark_delta(ctx.mark_enemy, StatusType.POISON, conversions * produced)

