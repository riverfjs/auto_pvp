"""Runtime execution for generated after-attack active buff actions."""

from __future__ import annotations

from roco.common.enums import SkillCategory
from roco.engine.kernel.core.ctx import StageCtx
from roco.engine.kernel.flow.action_runner import execute_action
from roco.engine.kernel.model.active_buffs import active_buff_id, iter_active_buffs
from roco.engine.kernel.model.state import KernelState, side
from roco.engine.kernel.residual.after_move import apply_after_move
from roco.generated.catalog import actions as catalog_actions


def after_attack_response_supported(buff_id: int) -> bool:
    return _trigger_action_id(buff_id) > 0


def trigger_after_attack_active_buffs(
    state: KernelState,
    attacker_side_id: int,
    attacker_slot: int,
    defender_side_id: int,
    defender_slot: int,
    skill_category: int,
    damage_dealt: int,
) -> KernelState:
    if damage_dealt <= 0 or skill_category not in (SkillCategory.PHYSICAL.value, SkillCategory.MAGICAL.value):
        return state
    defender_side = side(state, defender_side_id)
    defender = defender_side.pets[defender_slot]
    if defender.fainted or defender.active_buffs == 0:
        return state

    ctx = StageCtx()
    ctx.reset(defender_side_id, defender_slot, attacker_side_id, attacker_slot, 0)
    ctx.skill_category = skill_category
    ctx.damage_dealt = damage_dealt
    fired = False
    for slot_idx, lane in iter_active_buffs(defender.active_buffs):
        buff_id = active_buff_id(lane)
        action_id = _trigger_action_id(buff_id)
        if action_id <= 0:
            continue
        state = execute_action(
            state,
            ctx,
            action_id,
            actor_side=defender_side_id,
            actor_slot=defender_slot,
            target_side=attacker_side_id,
            target_slot=attacker_slot,
            source_ref=buff_id,
            source_skill_id=0,
            source_buff_id=buff_id,
            source_instance_id=slot_idx,
            trigger_event=0,
            action_flags=0,
            allow_extra_queue=False,
            depth=0,
        )
        fired = True
    if not fired:
        return state
    return apply_after_move(state, defender_side_id, defender_slot, attacker_side_id, attacker_slot, ctx)


def _trigger_action_id(buff_id: int) -> int:
    for row_buff_id, action_id in getattr(catalog_actions, "AFTER_ATTACK_TRIGGERS", ()):
        if int(row_buff_id) == int(buff_id):
            return int(action_id)
    return 0
