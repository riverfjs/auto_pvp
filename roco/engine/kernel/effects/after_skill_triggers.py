"""Runtime after-skill trigger execution for active buffs."""

from __future__ import annotations

from roco.engine.kernel.flow.action_runner import execute_action
from roco.engine.kernel.core.ctx import StageCtx
from roco.engine.kernel.model.active_buffs import active_buff_id, iter_active_buffs
from roco.engine.kernel.model.state import KernelState, side
from roco.engine.kernel.residual.after_move import apply_after_move
from roco.generated.catalog import actions as catalog_actions


def trigger_after_skill_active_buffs(
    state: KernelState,
    source_ctx: StageCtx,
    actor_side_id: int,
    actor_slot: int,
    target_side_id: int,
    target_slot: int,
) -> KernelState:
    actor = side(state, actor_side_id).pets[actor_slot]
    if actor.fainted or actor.active_buffs == 0:
        return state
    fired = False
    action_ctx = StageCtx()
    action_ctx.reset(actor_side_id, actor_slot, target_side_id, target_slot, source_ctx.skill_id)
    action_ctx.copy_move_observations_from(source_ctx)
    for _slot_idx, lane in iter_active_buffs(actor.active_buffs):
        row = _trigger_row(active_buff_id(lane))
        if row is None:
            continue
        _buff_id, action_id, raw_skill_dam_types = row
        if raw_skill_dam_types and source_ctx.skill_dam_type not in raw_skill_dam_types:
            continue
        state = execute_action(
            state,
            action_ctx,
            action_id,
            actor_side=actor_side_id,
            actor_slot=actor_slot,
            target_side=target_side_id,
            target_slot=target_slot,
            source_ref=0,
            source_skill_id=source_ctx.skill_id,
            source_buff_id=active_buff_id(lane),
            source_instance_id=_slot_idx,
            trigger_event=0,
            action_flags=0,
            allow_extra_queue=False,
            depth=0,
        )
        fired = True
    if not fired:
        return state
    return apply_after_move(state, actor_side_id, actor_slot, target_side_id, target_slot, action_ctx)


def _trigger_row(buff_id: int) -> tuple[int, int, tuple[int, ...]] | None:
    for row in getattr(catalog_actions, "AFTER_SKILL_TRIGGERS", ()):
        if int(row[0]) == buff_id:
            return row
    return None
