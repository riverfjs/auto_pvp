"""Fixed battle update kernel."""

from __future__ import annotations

from typing import NamedTuple

from roco.config.constants import ENERGY_GAIN_PER_TURN, MAX_ENERGY
from roco.engine.common.choices import ACTION_MOVE, ACTION_SWITCH, SIDE_A, SIDE_B, Choice
from roco.engine.common.packing import DevotionIdx, _unpack_devotion
from roco.engine.common.rng import next_rng
from roco.engine.enums import SkillCategory, WeatherType
from roco.engine.generated import catalog_hot as hot
from roco.engine.kernel.catalog import (
    ELEMENT_GROUND,
    SKILL_CATEGORY,
    SKILL_ELEMENT,
    SKILL_ENERGY,
    SKILL_FLAG_DEVOTION,
    SKILL_FLAGS,
    SKILL_HIT_COUNT,
    SKILL_POWER,
    STAT_SPEED,
    validate_catalog,
)
from roco.engine.kernel.ctx import StageCtx
from roco.engine.kernel.damage import damage, marked_skill_cost, marked_speed
from roco.engine.kernel.ops import TIMING_AFTER_MOVE, TIMING_CALC_DAMAGE, run_skill_timing
from roco.engine.kernel.residual import apply_after_move, end_turn
from roco.engine.kernel.state import (
    KernelState,
    PetState,
    SideState,
    active_pet,
    replace_pet,
    replace_side,
    side,
    weather_type,
)
from roco.engine.kernel.switch import check_winner, clear_barrel_after_action, faint_pet, switch

validate_catalog(hot)


class KernelResult(NamedTuple):
    state: KernelState
    winner: int
    first_side: int
    damage_a: int
    damage_b: int


def update(state: KernelState, c1: Choice, c2: Choice, options=()) -> KernelResult:
    state = _start_turn(state)
    first_side, rng = _order(state, c1, c2)
    state = state._replace(rng=rng)
    ctx = StageCtx()
    damage_a = 0
    damage_b = 0
    if first_side == SIDE_A:
        second_slot = state.side_b.active
        state, damage_a = _execute(state, SIDE_A, c1, SIDE_B, ctx, True)
        if state.side_b.pets[second_slot].fainted == 0:
            state, damage_b = _execute(state, SIDE_B, c2, SIDE_A, ctx, False)
    else:
        second_slot = state.side_a.active
        state, damage_b = _execute(state, SIDE_B, c2, SIDE_A, ctx, True)
        if state.side_a.pets[second_slot].fainted == 0:
            state, damage_a = _execute(state, SIDE_A, c1, SIDE_B, ctx, False)
    state = end_turn(state)
    state = check_winner(state)
    return KernelResult(state, state.winner, first_side, damage_a, damage_b)


def _start_turn(state: KernelState) -> KernelState:
    side_a = _gain_energy(state.side_a)
    side_b = _gain_energy(state.side_b)
    return state._replace(turn=state.turn + 1, side_a=side_a, side_b=side_b)


def _gain_energy(side_state: SideState) -> SideState:
    pets = []
    for pet in side_state.pets:
        if pet.fainted:
            pets.append(pet)
        else:
            pets.append(pet._replace(current_energy=min(MAX_ENERGY, pet.current_energy + ENERGY_GAIN_PER_TURN)))
    return side_state._replace(pets=tuple(pets))


def _order(state: KernelState, c1: Choice, c2: Choice) -> tuple[int, int]:
    pri_a = _priority(c1)
    pri_b = _priority(c2)
    if pri_a != pri_b:
        return (SIDE_A if pri_a > pri_b else SIDE_B, state.rng)
    speed_a = marked_speed(_speed(active_pet(state.side_a)), state.side_a.marks)
    speed_b = marked_speed(_speed(active_pet(state.side_b)), state.side_b.marks)
    if speed_a != speed_b:
        return (SIDE_A if speed_a > speed_b else SIDE_B, state.rng)
    rng = next_rng(state.rng)
    return (SIDE_A if rng & 1 else SIDE_B, rng)


def _priority(choice: Choice) -> int:
    if choice.action_code == ACTION_SWITCH:
        return 6
    return 0


def _execute(
    state: KernelState,
    actor_side_id: int,
    choice: Choice,
    target_side_id: int,
    ctx: StageCtx,
    first_strike: bool,
) -> tuple[KernelState, int]:
    actor_side = side(state, actor_side_id)
    target_side = side(state, target_side_id)
    actor_slot = actor_side.active
    target_slot = target_side.active
    actor = actor_side.pets[actor_slot]
    target = target_side.pets[target_slot]
    if actor.fainted:
        return state, 0
    if choice.action_code == ACTION_SWITCH:
        return switch(state, actor_side_id, choice.data), 0
    if choice.action_code != ACTION_MOVE:
        return state, 0
    if choice.data < 0 or choice.data >= 4:
        return state, 0
    skill_id = actor_side.moves[actor_slot][choice.data]
    if skill_id <= 0:
        return state, 0
    skill = hot.SKILLS[skill_id]
    cost = skill[SKILL_ENERGY]
    is_attack = skill[SKILL_CATEGORY] in (SkillCategory.PHYSICAL.value, SkillCategory.MAGICAL.value)
    cost = marked_skill_cost(cost, actor_side.marks, is_attack)
    devotion_active = bool(skill[SKILL_FLAGS] & SKILL_FLAG_DEVOTION)
    if devotion_active:
        cost = max(0, cost - _unpack_devotion(actor_side.devotion, DevotionIdx.JIAMEI))
    if weather_type(state.weather) == WeatherType.SANDSTORM.value and skill[SKILL_ELEMENT] == ELEMENT_GROUND:
        cost //= 2
    if actor.current_energy < cost:
        return state, 0
    actor = actor._replace(current_energy=max(0, actor.current_energy - cost))
    actor_side = replace_pet(actor_side, actor_slot, actor)
    state = replace_side(state, actor_side_id, actor_side)
    dealt = 0
    ctx.reset(actor_side_id, actor_slot, target_side_id, target_slot, skill_id)
    ctx.power = skill[SKILL_POWER]
    ctx.hit_count = skill[SKILL_HIT_COUNT]
    if devotion_active:
        ctx.power_bps += _unpack_devotion(actor_side.devotion, DevotionIdx.FEIDUAN) * 1000
        ctx.hit_count += _unpack_devotion(actor_side.devotion, DevotionIdx.CHONGQUN)
    if is_attack:
        run_skill_timing(hot.SKILL_EFFECT_ROWS, hot.SKILL_EFFECT_RANGES[skill_id], TIMING_CALC_DAMAGE, ctx)
        dealt = damage(actor, target, skill, ctx, state.weather, actor_side.marks, target_side.marks, first_strike)
        next_hp = target.current_hp - dealt
        if next_hp <= 0 and target.cute >= 5:
            target = target._replace(current_hp=1, cute=target.cute - 5)
        else:
            target = target._replace(current_hp=max(0, next_hp))
        target_side = replace_pet(target_side, target_slot, target)
        state = replace_side(state, target_side_id, target_side)
        if target.current_hp <= 0:
            state = faint_pet(state, target_side_id, target_slot, actor_side_id, actor_slot)
    run_skill_timing(hot.SKILL_EFFECT_ROWS, hot.SKILL_EFFECT_RANGES[skill_id], TIMING_AFTER_MOVE, ctx)
    state = apply_after_move(state, actor_side_id, actor_slot, target_side_id, target_slot, ctx)
    state = clear_barrel_after_action(state, actor_side_id, actor_slot)
    return state, dealt


def _speed(pet: PetState) -> int:
    return hot.PETS[pet.pet_id][STAT_SPEED]
