"""Conservative forced extra-skill resolution for pak ET_SERIES_SKILL."""

from __future__ import annotations

from roco.common.enums import Element, SkillCategory, StatusType
from roco.common.packing import MarkIdx, _unpack_buff, _unpack_element_u8, _unpack_mark
from roco.engine.kernel.flow.action_runner import drain_pending_actions
from roco.engine.kernel.core.catalog import (
    PET_ABILITY,
    PET_PRIMARY,
    PET_SECONDARY,
    SKILL_CATEGORY,
    SKILL_ELEMENT,
    SKILL_ENERGY,
    SKILL_FLAGS,
    SKILL_DAM_TYPE,
    SKILL_HIT_COUNT,
    SKILL_POWER,
    STAT_HP,
)
from roco.engine.kernel.core.ctx import StageCtx
from roco.engine.kernel.effects.damage import consume_triggered_meteor_marks, damage
from roco.engine.kernel.core.rows import (
    TIMING_HOOK_TAKE_DAMAGE,
    TIMING_PAK_BEFORE_HURT,
    TIMING_PAK_ROUND_CALC_START,
)
from roco.engine.kernel.core.dispatch import run_skill_timing
from roco.engine.kernel.residual import apply_after_move
from roco.engine.kernel.model.state import KernelState, replace_pet, replace_side, side, status_stack
from roco.engine.kernel.flow.switch import faint_pet
from roco.generated.catalog import hot


def drain_extra_skill_queue(
    state: KernelState,
    ctx: StageCtx,
    actor_side_id: int,
    actor_slot: int,
    target_side_id: int,
    target_slot: int,
    first_strike: bool,
) -> KernelState:
    queue = tuple(ctx.extra_skill_queue)
    ctx.extra_skill_queue = ()
    for skill_id, _policy in queue:
        state = execute_forced_extra_skill(
            state,
            actor_side_id,
            actor_slot,
            target_side_id,
            target_slot,
            int(skill_id),
            first_strike,
        )
    return state


def execute_forced_extra_skill(
    state: KernelState,
    actor_side_id: int,
    actor_slot: int,
    target_side_id: int,
    target_slot: int,
    skill_id: int,
    first_strike: bool,
) -> KernelState:
    """Run skill core only; skip outer move lifecycle and recursion drain."""

    if skill_id <= 0 or skill_id >= len(hot.SKILLS):
        return state
    actor_side = side(state, actor_side_id)
    target_side = side(state, target_side_id)
    if actor_slot >= len(actor_side.pets) or target_slot >= len(target_side.pets):
        return state
    actor = actor_side.pets[actor_slot]
    target = target_side.pets[target_slot]
    if actor.fainted or target.fainted:
        return state
    skill = hot.SKILLS[skill_id]
    if not skill or skill[0] != skill_id:
        return state
    ctx = StageCtx()
    ctx.reset(actor_side_id, actor_slot, target_side_id, target_slot, skill_id)
    _populate_core_ctx(ctx, state, actor_side_id, actor_slot, target_side_id, target_slot, skill, first_strike)
    run_skill_timing(hot.SKILL_EFFECT_ROWS, hot.SKILL_EFFECT_RANGES[skill_id], TIMING_PAK_ROUND_CALC_START, ctx)
    state = _drain_action_group(state, ctx, actor_side_id, actor_slot, target_side_id, target_slot, skill_id, TIMING_PAK_ROUND_CALC_START)
    if skill[SKILL_CATEGORY] in (SkillCategory.PHYSICAL.value, SkillCategory.MAGICAL.value):
        state = _resolve_forced_damage(state, ctx, actor_side_id, actor_slot, target_side_id, target_slot, skill, first_strike)
    run_skill_timing(hot.SKILL_EFFECT_ROWS, hot.SKILL_EFFECT_RANGES[skill_id], TIMING_PAK_BEFORE_HURT, ctx)
    state = _drain_action_group(state, ctx, actor_side_id, actor_slot, target_side_id, target_slot, skill_id, TIMING_PAK_BEFORE_HURT)
    return apply_after_move(state, actor_side_id, actor_slot, target_side_id, target_slot, ctx)


def _resolve_forced_damage(
    state: KernelState,
    ctx: StageCtx,
    actor_side_id: int,
    actor_slot: int,
    target_side_id: int,
    target_slot: int,
    skill: tuple[int, ...],
    first_strike: bool,
) -> KernelState:
    actor_side = side(state, actor_side_id)
    target_side = side(state, target_side_id)
    actor = actor_side.pets[actor_slot]
    target = target_side.pets[target_slot]
    dealt = damage(actor, target, skill, ctx, state.weather, actor_side.marks, target_side.marks, first_strike)
    ctx.damage_dealt = dealt
    if dealt > 0:
        _run_ability_timing(target, TIMING_HOOK_TAKE_DAMAGE, ctx)
        state = _drain_action_group(state, ctx, actor_side_id, actor_slot, target_side_id, target_slot, ctx.skill_id, TIMING_HOOK_TAKE_DAMAGE)
    target_side = target_side._replace(
        marks=consume_triggered_meteor_marks(actor, skill, target_side.marks, dealt)
    )
    target = target._replace(current_hp=max(0, target.current_hp - dealt))
    target_side = replace_pet(target_side, target_slot, target)
    state = replace_side(state, target_side_id, target_side)
    if target.current_hp <= 0:
        state = faint_pet(state, target_side_id, target_slot, actor_side_id, actor_slot)
    return state


def _run_ability_timing(actor, timing: int, ctx: StageCtx) -> None:
    ability_id = hot.PETS[actor.pet_id][PET_ABILITY]
    if ability_id <= 0 or ability_id >= len(hot.ABILITY_EFFECT_RANGES):
        return
    run_skill_timing(hot.ABILITY_EFFECT_ROWS, hot.ABILITY_EFFECT_RANGES[ability_id], timing, ctx)


def _drain_action_group(
    state: KernelState,
    ctx: StageCtx,
    actor_side_id: int,
    actor_slot: int,
    target_side_id: int,
    target_slot: int,
    skill_id: int,
    trigger_event: int,
) -> KernelState:
    if not ctx.pending_actions:
        return state
    return drain_pending_actions(
        state,
        ctx,
        actor_side=actor_side_id,
        actor_slot=actor_slot,
        target_side=target_side_id,
        target_slot=target_slot,
        source_skill_id=skill_id,
        trigger_event=trigger_event,
        allow_extra_queue=False,
    )


def _populate_core_ctx(
    ctx: StageCtx,
    state: KernelState,
    actor_side_id: int,
    actor_slot: int,
    target_side_id: int,
    target_slot: int,
    skill: tuple[int, ...],
    first_strike: bool,
) -> None:
    actor_side = side(state, actor_side_id)
    target_side = side(state, target_side_id)
    actor = actor_side.pets[actor_slot]
    target = target_side.pets[target_slot]
    actor_row = hot.PETS[actor.pet_id]
    target_row = hot.PETS[target.pet_id]
    ctx.skill_element = skill[SKILL_ELEMENT]
    ctx.skill_dam_type = skill[SKILL_DAM_TYPE]
    ctx.skill_category = skill[SKILL_CATEGORY]
    ctx.skill_energy = skill[SKILL_ENERGY]
    ctx.skill_flags = skill[SKILL_FLAGS]
    ctx.actor_primary = actor_row[PET_PRIMARY]
    ctx.actor_secondary = actor_row[PET_SECONDARY]
    ctx.actor_bloodline = actor_side.bloodlines[actor_slot] if actor_slot < len(actor_side.bloodlines) else -1
    ctx.actor_energy = actor.current_energy
    ctx.actor_cute = actor.cute
    ctx.actor_poison_stacks = status_stack(actor, StatusType.POISON)
    ctx.actor_counter_count = actor.counter_success_count
    ctx.actor_hp_lost_quarters = max(0, actor_row[STAT_HP] - actor.current_hp) * 4 // max(1, actor_row[STAT_HP])
    ctx.side_skill_counts = actor_side.skill_counts
    ctx.side_same_skill_count = sum(
        1
        for moves in actor_side.moves
        for side_skill_id in moves
        if side_skill_id == ctx.skill_id
    )
    ctx.side_counter_count = actor_side.counter_count
    ctx.side_status_skill_count = actor_side.status_skill_count
    ctx.side_defense_skill_count = actor_side.defense_skill_count
    ctx.side_skill_dam_type_counts = actor_side.skill_dam_type_counts
    ctx.target_primary = target_row[PET_PRIMARY]
    ctx.target_secondary = target_row[PET_SECONDARY]
    ctx.target_bloodline = target_side.bloodlines[target_slot] if target_slot < len(target_side.bloodlines) else -1
    ctx.target_energy = target.current_energy
    (
        ctx.target_equipped_skill_type_count,
        ctx.target_equipped_skill_total_cost,
    ) = _equipped_skill_type_count_and_total_cost(target_side, target_slot)
    ctx.target_mark_total = sum(_unpack_mark(target_side.marks, idx) for idx in MarkIdx)
    ctx.target_meteor_mark_stacks = _unpack_mark(target_side.marks, MarkIdx.METEOR)
    ctx.target_positive_buff_layers = _positive_buff_layers(target.buff_stages)
    ctx.target_poison_stacks = status_stack(target, StatusType.POISON)
    ctx.target_poison_effect_stacks = (
        ctx.target_poison_stacks + _unpack_mark(target_side.marks, MarkIdx.POISON)
    )
    ctx.power = (
        skill[SKILL_POWER]
        + actor.global_power_bonus
        + _unpack_element_u8(actor.element_power_flat, Element(skill[SKILL_ELEMENT]))
    )
    ctx.hit_count = max(1, skill[SKILL_HIT_COUNT] + actor.hit_delta)
    ctx.power_bps += _unpack_element_u8(actor.element_power_bps, Element(skill[SKILL_ELEMENT])) * 100
    ctx.first_strike = 1 if first_strike else 0


def _positive_buff_layers(packed: int) -> int:
    total = 0
    for idx in range(7):
        total += max(0, _unpack_buff(packed, idx))
    return total


def _equipped_skill_type_count_and_total_cost(side_state, slot: int) -> tuple[int, int]:
    if slot < 0 or slot >= len(side_state.moves):
        return 0, 0
    skill_types: set[int] = set()
    total_cost = 0
    for skill_id in side_state.moves[slot]:
        if skill_id <= 0 or skill_id >= len(hot.SKILLS):
            continue
        skill = hot.SKILLS[skill_id]
        skill_dam_type = int(skill[SKILL_DAM_TYPE])
        if skill_dam_type > 0:
            skill_types.add(skill_dam_type)
        total_cost += max(0, int(skill[SKILL_ENERGY]))
    return len(skill_types), total_cost
