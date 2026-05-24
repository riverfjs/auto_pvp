"""End-of-turn orchestration.

``end_turn`` runs the residual phases in the order an Roco round needs:

1. Leech tick (status_ticks.tick_leech)
2. Mark residuals (mark_ticks.tick_marks)
3. Ability TURN_END effects (skip when either active pet has the
   ``TURN_END_SKIP`` ability flag)
4. Skill TURN_END effects for the skill each side just used
5. Weather residuals + turn decay (weather_ticks.tick_weather)
6. Status tick (status_ticks.tick_status)
7. Per-turn cost-mod cleanup
"""

from __future__ import annotations

from roco.common.enums import AbilityFlag
from roco.common.packing import _tick_cooldowns
from roco.engine.common.choices import SIDE_A, SIDE_B
from roco.engine.kernel.active_buffs import tick_active_buffs
from roco.engine.kernel.catalog import PET_ABILITY, PET_PRIMARY, PET_SECONDARY
from roco.engine.kernel.ctx import StageCtx
from roco.engine.kernel.op_rows import TIMING_PAK_BEFORE_ADD
from roco.engine.kernel.ops import run_skill_timing
from roco.engine.kernel.residual.after_move import apply_after_move
from roco.engine.kernel.residual.mark_ticks import tick_marks
from roco.engine.kernel.residual.status_ticks import tick_leech, tick_status
from roco.engine.kernel.residual.weather_ticks import tick_weather
from roco.engine.kernel.state import KernelState, side, tick_cost_mod
from roco.engine.kernel.switch import mark_zero_hp_fainted
from roco.generated import catalog_hot as hot


def end_turn(state: KernelState, skill_a_id: int = 0, skill_b_id: int = 0) -> KernelState:
    state = tick_leech(state)
    state = tick_marks(state)
    if not _turn_end_effects_reduced(state):
        state = tick_ability_turn_end(state)
    state = tick_skill_turn_end(state, skill_a_id, skill_b_id)
    state = tick_weather(state)
    state = tick_status(state)
    state = tick_side_cost_mods(state)
    return mark_zero_hp_fainted(state)


def _turn_end_effects_reduced(state: KernelState) -> bool:
    return bool(
        active_pet_flags(state.side_a) & int(AbilityFlag.TURN_END_SKIP)
        or active_pet_flags(state.side_b) & int(AbilityFlag.TURN_END_SKIP)
    )


def active_pet_flags(side_state) -> int:
    return side_state.pets[side_state.active].ability_flags


def tick_side_cost_mods(state: KernelState) -> KernelState:
    return state._replace(
        side_a=_tick_side_turn_state(state.side_a),
        side_b=_tick_side_turn_state(state.side_b),
    )


def _tick_side_turn_state(side_state):
    pets = tuple(
        pet._replace(
            anti_heal_multiplier=0,
            cooldowns=_tick_cooldowns(pet.cooldowns),
            active_buffs=tick_active_buffs(pet.active_buffs),
        )
        if pet.anti_heal_multiplier or pet.cooldowns or pet.active_buffs else pet
        for pet in side_state.pets
    )
    return side_state._replace(cost_mods=tick_cost_mod(side_state.cost_mods), pets=pets)


def tick_skill_turn_end(state: KernelState, skill_a_id: int, skill_b_id: int) -> KernelState:
    """Run SKILL effect rows whose ``cast_moment`` is TURN_END (pak code 12).

    Pak commonly attaches an actor's own buff/mark application to the
    turn-end timing (e.g. 风起's wind mark, 焚烧烙印's burn payload).
    ``mechanics.update`` captures each side's chosen skill id at turn start
    and threads it here so those rows actually fire.
    """
    for side_id, target_side_id, skill_id in (
        (SIDE_A, SIDE_B, skill_a_id),
        (SIDE_B, SIDE_A, skill_b_id),
    ):
        if skill_id <= 0 or skill_id >= len(hot.SKILL_EFFECT_RANGES):
            continue
        state = _run_actor_turn_end(state, side_id, target_side_id, hot.SKILL_EFFECT_ROWS, hot.SKILL_EFFECT_RANGES[skill_id], skill_id)
    return state


def tick_ability_turn_end(state: KernelState) -> KernelState:
    for side_id, target_side_id in ((SIDE_A, SIDE_B), (SIDE_B, SIDE_A)):
        side_state = side(state, side_id)
        pet = side_state.pets[side_state.active]
        if pet.fainted:
            continue
        ability_id = hot.PETS[pet.pet_id][PET_ABILITY]
        if ability_id <= 0 or ability_id >= len(hot.ABILITY_EFFECT_RANGES):
            continue
        state = _run_actor_turn_end(state, side_id, target_side_id, hot.ABILITY_EFFECT_ROWS, hot.ABILITY_EFFECT_RANGES[ability_id], 0)
    return state


def _run_actor_turn_end(
    state: KernelState,
    side_id: int,
    target_side_id: int,
    rows,
    rng_range,
    skill_id: int,
) -> KernelState:
    """Shared body for ``tick_skill_turn_end`` and ``tick_ability_turn_end``."""
    side_state = side(state, side_id)
    target_side = side(state, target_side_id)
    slot = side_state.active
    target_slot = target_side.active
    pet = side_state.pets[slot]
    if pet.fainted:
        return state
    ctx = StageCtx()
    ctx.reset(side_id, slot, target_side_id, target_slot, skill_id)
    pet_row = hot.PETS[pet.pet_id]
    target_row = hot.PETS[target_side.pets[target_slot].pet_id]
    ctx.actor_primary = pet_row[PET_PRIMARY]
    ctx.actor_secondary = pet_row[PET_SECONDARY]
    ctx.actor_bloodline = side_state.bloodlines[slot] if slot < len(side_state.bloodlines) else -1
    ctx.actor_energy = pet.current_energy
    ctx.target_primary = target_row[PET_PRIMARY]
    ctx.target_secondary = target_row[PET_SECONDARY]
    ctx.target_bloodline = target_side.bloodlines[target_slot] if target_slot < len(target_side.bloodlines) else -1
    # Each actor reads only its own dispel tally so opposing actors that
    # also cleared marks this turn don't bleed into this skill's
    # mark→burn payload.
    ctx.marks_dispelled = (
        state.marks_dispelled_a if side_id == SIDE_A else state.marks_dispelled_b
    )
    run_skill_timing(rows, rng_range, TIMING_PAK_BEFORE_ADD, ctx)
    return apply_after_move(state, side_id, slot, target_side_id, target_slot, ctx)
