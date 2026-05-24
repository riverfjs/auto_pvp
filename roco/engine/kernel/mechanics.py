"""Fixed battle update kernel."""

from __future__ import annotations

from typing import NamedTuple

from roco.engine.common.choices import ACTION_FOCUS, ACTION_MAGIC, ACTION_MOVE, ACTION_SWITCH, SIDE_A, SIDE_B, Choice
from roco.common.packing import (
    DevotionIdx,
    MarkIdx,
    _cooldown_at,
    _inc_skill_count,
    _inc_u8_count,
    _unpack_devotion,
    _unpack_element_u8,
    _unpack_mark,
    _unpack_skill_count,
)
from roco.common.constants import (
    BPS,
    HP_FOR_ENERGY_PCT_BPS,
    MAGIC_LEADER_TRANSFORM,
    MAGIC_WILLPOWER,
    WILLPOWER_COUNTER_STATUS_BPS,
)
from roco.engine.kernel.actions import (
    can_pay_hp_for_energy,
    focus as _focus,
    leader_transform as _leader_transform,
    pay_skill_cost_with_hp,
)
from roco.common.enums import AbilityFlag, Element, SkillCategory, StatusType, WeatherType
from roco.generated import catalog_hot as hot
from roco.generated.bloodline_magic import WILLPOWER_RUNTIME_SKILL_BY_BLOODLINE_ID
from roco.engine.kernel.catalog import (
    ELEMENT_GROUND,
    PET_ABILITY,
    SKILL_CATEGORY,
    SKILL_ELEMENT,
    SKILL_ENERGY,
    SKILL_FLAG_AGILITY,
    SKILL_FLAG_DEVOTION,
    SKILL_FLAGS,
    SKILL_DAM_TYPE,
    SKILL_HIT_COUNT,
    SKILL_POWER,
    STAT_HP,
    PET_PRIMARY,
    PET_SECONDARY,
    validate_catalog,
)
from roco.engine.kernel.counter import fire_counter_skill
from roco.engine.kernel.ctx import StageCtx
from roco.engine.kernel.damage import damage, marked_skill_cost
from roco.engine.kernel.op_rows import (
    TIMING_AFTER_MOVE,
    TIMING_BEFORE_MOVE,
    TIMING_CALC_DAMAGE,
    TIMING_TAKE_DAMAGE,
)
from roco.engine.kernel.ops import run_skill_timing
from roco.engine.kernel.residual import apply_after_move, end_turn
from roco.engine.kernel.state import (
    KernelState,
    PetState,
    cost_mod_amount,
    replace_pet,
    replace_side,
    side,
    status_stack,
    weather_type,
)
from roco.engine.kernel.switch import check_winner, clear_barrel_after_action, faint_pet, switch
from roco.engine.kernel.turn_flow import (
    borrowed_skill_id,
    choice_category,
    choice_to_skill_id,
    order,
    start_turn,
    target_skill_energy,
)

validate_catalog(hot)


class KernelResult(NamedTuple):
    state: KernelState
    winner: int
    first_side: int
    damage_a: int
    damage_b: int


def update(state: KernelState, c1: Choice, c2: Choice, options=()) -> KernelResult:
    state = start_turn(state)
    first_side, rng = order(state, c1, c2)
    state = state._replace(rng=rng)
    skill_a = choice_to_skill_id(state, SIDE_A, c1)
    skill_b = choice_to_skill_id(state, SIDE_B, c2)
    ctx = StageCtx()
    damage_a = 0
    damage_b = 0
    category_a = choice_category(state, SIDE_A, c1)
    category_b = choice_category(state, SIDE_B, c2)
    if first_side == SIDE_A:
        second_slot = state.side_b.active
        state, damage_a = _execute(state, SIDE_A, c1, SIDE_B, ctx, True, category_b, c2.data)
        if state.side_b.pets[second_slot].fainted == 0:
            state, damage_b = _execute(state, SIDE_B, c2, SIDE_A, ctx, False, category_a, c1.data)
    else:
        second_slot = state.side_a.active
        state, damage_b = _execute(state, SIDE_B, c2, SIDE_A, ctx, True, category_a, c1.data)
        if state.side_a.pets[second_slot].fainted == 0:
            state, damage_a = _execute(state, SIDE_A, c1, SIDE_B, ctx, False, category_b, c2.data)
    state = end_turn(state, skill_a, skill_b)
    state = check_winner(state)
    return KernelResult(state, state.winner, first_side, damage_a, damage_b)


def _execute(
    state: KernelState,
    actor_side_id: int,
    choice: Choice,
    target_side_id: int,
    ctx: StageCtx,
    first_strike: bool,
    target_category: int,
    target_choice_slot: int,
) -> tuple[KernelState, int]:
    actor_side = side(state, actor_side_id)
    target_side = side(state, target_side_id)
    actor_slot = actor_side.active
    target_slot = target_side.active
    actor = actor_side.pets[actor_slot]
    target = target_side.pets[target_slot]
    if actor.fainted:
        return state, 0
    if actor.priority_boost:
        actor = actor._replace(priority_boost=0)
        actor_side = replace_pet(actor_side, actor_slot, actor)
        state = replace_side(state, actor_side_id, actor_side)
    if choice.action_code == ACTION_SWITCH:
        return switch(state, actor_side_id, choice.data), 0
    if choice.action_code == ACTION_FOCUS:
        return _focus(state, actor_side_id), 0
    if choice.action_code == ACTION_MAGIC:
        if actor_side.bloodline_magic_id == MAGIC_LEADER_TRANSFORM:
            return _leader_transform(state, actor_side_id, actor_slot), 0
        if actor_side.bloodline_magic_id != MAGIC_WILLPOWER or actor_side.willpower_uses <= 0:
            return state, 0
        bloodline = actor_side.bloodlines[actor_slot] if actor_slot < len(actor_side.bloodlines) else -1
        skill = WILLPOWER_RUNTIME_SKILL_BY_BLOODLINE_ID.get(bloodline)
        if skill is None:
            return state, 0
        skill_id = 0
        actor_side = actor_side._replace(willpower_uses=actor_side.willpower_uses - 1)
        state = replace_side(state, actor_side_id, actor_side)
    elif choice.action_code != ACTION_MOVE:
        return state, 0
    else:
        if choice.data < 0 or choice.data >= 4:
            return state, 0
        skill_id = actor_side.moves[actor_slot][choice.data]
        if skill_id <= 0:
            return state, 0
        if _cooldown_at(actor.cooldowns, choice.data) > 0:
            return _focus(state, actor_side_id), 0
        borrowed = borrowed_skill_id(actor_side, actor_slot, skill_id, state.rng)
        if borrowed > 0:
            skill_id = borrowed
        if actor.ability_flags & int(AbilityFlag.SKILL_SLOT_LOCK) and choice.data != 0:
            return _focus(state, actor_side_id), 0
        skill = hot.SKILLS[skill_id]
    cost = skill[SKILL_ENERGY]
    is_attack = skill[SKILL_CATEGORY] in (SkillCategory.PHYSICAL.value, SkillCategory.MAGICAL.value)
    cost = marked_skill_cost(cost, actor_side.marks, is_attack)
    devotion_active = bool(skill[SKILL_FLAGS] & SKILL_FLAG_DEVOTION)
    if devotion_active:
        cost = max(0, cost - _unpack_devotion(actor_side.devotion, DevotionIdx.JIAMEI))
    if weather_type(state.weather) == WeatherType.SANDSTORM.value and skill[SKILL_ELEMENT] == ELEMENT_GROUND:
        cost //= 2
    cost += actor.global_cost_delta
    cost -= _unpack_skill_count(actor.element_cost_reduce, Element(skill[SKILL_ELEMENT]))
    cost += cost_mod_amount(actor_side.cost_mods, choice.data if choice.action_code == ACTION_MOVE else -1, skill[SKILL_CATEGORY])
    dealt = 0
    ctx.reset(actor_side_id, actor_slot, target_side_id, target_slot, skill_id)
    ctx.skill_slot = choice.data if choice.action_code == ACTION_MOVE and 0 <= choice.data < 4 else -1
    actor_row = hot.PETS[actor.pet_id]
    target_row = hot.PETS[target.pet_id]
    ctx.skill_element = skill[SKILL_ELEMENT]
    ctx.skill_category = skill[SKILL_CATEGORY]
    ctx.skill_energy = skill[SKILL_ENERGY]
    ctx.skill_flags = skill[SKILL_FLAGS]
    ctx.actor_primary = actor_row[PET_PRIMARY]
    ctx.actor_secondary = actor_row[PET_SECONDARY]
    ctx.actor_bloodline = actor_side.bloodlines[actor_slot] if actor_slot < len(actor_side.bloodlines) else -1
    ctx.actor_energy = actor.current_energy
    ctx.actor_cute = actor.cute
    ctx.actor_counter_count = actor.counter_success_count
    ctx.actor_hp_lost_quarters = max(0, actor_row[STAT_HP] - actor.current_hp) * 4 // max(1, actor_row[STAT_HP])
    ctx.side_skill_counts = actor_side.skill_counts
    ctx.side_same_skill_count = sum(
        1
        for moves in actor_side.moves
        for side_skill_id in moves
        if side_skill_id == skill_id
    )
    ctx.side_counter_count = actor_side.counter_count
    ctx.side_status_skill_count = actor_side.status_skill_count
    ctx.side_defense_skill_count = actor_side.defense_skill_count
    ctx.side_skill_dam_type_counts = actor_side.skill_dam_type_counts
    ctx.target_primary = target_row[PET_PRIMARY]
    ctx.target_secondary = target_row[PET_SECONDARY]
    ctx.target_bloodline = target_side.bloodlines[target_slot] if target_slot < len(target_side.bloodlines) else -1
    ctx.target_skill_slot = target_choice_slot if 0 <= target_choice_slot < 4 else -1
    ctx.target_skill_energy = target_skill_energy(target_side, target_slot, ctx.target_skill_slot)
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
    ctx.counter_category = 2 if target_category in (SkillCategory.DEFENSE.value, SkillCategory.STATUS.value) else 1
    ctx.counter_success = 1 if choice.action_code == ACTION_MAGIC and ctx.counter_category == 2 else 0
    ctx.first_strike = 1 if first_strike else 0
    if devotion_active:
        ctx.power_bps += _unpack_devotion(actor_side.devotion, DevotionIdx.FEIDUAN) * 1000
        ctx.hit_count += _unpack_devotion(actor_side.devotion, DevotionIdx.CHONGQUN)
    _run_ability_timing(actor, TIMING_BEFORE_MOVE, ctx)
    run_skill_timing(hot.SKILL_EFFECT_ROWS, hot.SKILL_EFFECT_RANGES[skill_id], TIMING_BEFORE_MOVE, ctx)
    cost = max(0, cost - ctx.cost_delta if actor.ability_flags & int(AbilityFlag.COST_INVERT) else cost + ctx.cost_delta)
    if choice.action_code == ACTION_MAGIC and ctx.counter_success:
        ctx.power_bps = ctx.power_bps * WILLPOWER_COUNTER_STATUS_BPS // BPS
    if actor.current_energy < cost:
        hp_for_energy = ctx.hp_for_energy
        if actor.ability_flags & int(AbilityFlag.HP_FOR_ENERGY):
            hp_for_energy = hp_for_energy or HP_FOR_ENERGY_PCT_BPS
        if hp_for_energy and can_pay_hp_for_energy(actor, cost - actor.current_energy, hp_for_energy):
            actor = pay_skill_cost_with_hp(actor, cost, hp_for_energy)
            actor_side = replace_pet(actor_side, actor_slot, actor)
            state = replace_side(state, actor_side_id, actor_side)
        else:
            return _focus(state, actor_side_id), 0
    else:
        actor = actor._replace(current_energy=max(0, actor.current_energy - cost))
        actor_side = replace_pet(actor_side, actor_slot, actor)
        state = replace_side(state, actor_side_id, actor_side)
    if is_attack and first_strike:
        _run_ability_timing(actor, TIMING_CALC_DAMAGE, ctx)
    # Run the skill's CALC_DAMAGE side effects regardless of whether the
    # skill itself does damage — pak attaches things like dispel-marks
    # (焚烧烙印 / 1042008) to ``cast_moment=6`` on non-attack skills, and
    # gating them behind ``is_attack`` would just silently drop them.
    run_skill_timing(hot.SKILL_EFFECT_ROWS, hot.SKILL_EFFECT_RANGES[skill_id], TIMING_CALC_DAMAGE, ctx)
    if is_attack:
        dealt = damage(actor, target, skill, ctx, state.weather, actor_side.marks, target_side.marks, first_strike)
        ctx.damage_dealt = dealt
        if dealt > 0:
            _run_ability_timing(target, TIMING_TAKE_DAMAGE, ctx)
        next_hp = target.current_hp - dealt
        if next_hp <= 0 and target.ability_flags & int(AbilityFlag.CUTE_LETHAL_SHIELD):
            target = target._replace(current_hp=1, cute=target.cute + 1)
        elif next_hp <= 0 and target.cute >= 5:
            target = target._replace(current_hp=1, cute=target.cute - 5)
        else:
            target = target._replace(current_hp=max(0, next_hp))
        target_side = replace_pet(target_side, target_slot, target)
        state = replace_side(state, target_side_id, target_side)
        if target.current_hp <= 0:
            state = faint_pet(state, target_side_id, target_slot, actor_side_id, actor_slot)
        # Counter-trigger consume: if the defender's side has an armed
        # "应对！X" counter (installed earlier by the pak 1031xxx family),
        # fire it now against the attacker.  One-shot — clears after firing
        # whether or not the attacker is still alive.
        if dealt > 0 and target.current_hp > 0:
            state, counter_dealt = fire_counter_skill(
                state, actor_side_id, actor_slot, target_side_id, target_slot, first_strike
            )
            if counter_dealt:
                actor_side = side(state, actor_side_id)
                actor = actor_side.pets[actor_slot]
                target_side = side(state, target_side_id)
                target = target_side.pets[target_slot]
    if skill_id > 0:
        actor_side = side(state, actor_side_id)
        actor = actor_side.pets[actor_slot]
        uses = 1
        if actor.ability_flags & int(AbilityFlag.FIRST_ACTION_EXTRA_USE) and actor.first_action_done == 0:
            uses += 1
            actor = actor._replace(first_action_done=1)
            actor_side = replace_pet(actor_side, actor_slot, actor)
        skill_counts = actor_side.skill_counts
        for _ in range(uses):
            skill_counts = _inc_skill_count(skill_counts, Element(skill[SKILL_ELEMENT]))
        status_count = actor_side.status_skill_count + (uses if skill[SKILL_CATEGORY] == SkillCategory.STATUS.value else 0)
        defense_count = actor_side.defense_skill_count + (uses if skill[SKILL_CATEGORY] == SkillCategory.DEFENSE.value else 0)
        skill_dam_type_counts = actor_side.skill_dam_type_counts
        for _ in range(uses):
            skill_dam_type_counts = _inc_u8_count(skill_dam_type_counts, skill[SKILL_DAM_TYPE])
        actor_side = actor_side._replace(
            skill_counts=skill_counts,
            status_skill_count=min(255, status_count),
            defense_skill_count=min(255, defense_count),
            skill_dam_type_counts=skill_dam_type_counts,
        )
        state = replace_side(state, actor_side_id, actor_side)
    if ctx.counter_success:
        actor_side = side(state, actor_side_id)
        actor = actor_side.pets[actor_slot]
        actor = actor._replace(counter_success_count=min(255, actor.counter_success_count + 1))
        ctx.actor_counter_count = actor.counter_success_count
        actor_side = replace_pet(actor_side, actor_slot, actor)._replace(counter_count=min(255, actor_side.counter_count + 1))
        state = replace_side(state, actor_side_id, actor_side)
    # ``ctx.actor_energy`` was set to the actor's *pre-cost* energy back at the
    # top of _execute (so BEFORE_MOVE / CALC_DAMAGE ops see the same reading
    # pak documents for those timings).  By the time TIMING_AFTER_MOVE runs,
    # the skill cost, HP-for-energy substitution, counter, and first-action
    # branches have all settled — refresh the reading once here so AFTER_MOVE
    # ops (e.g. ``op_auto_switch_on_zero_energy`` for buff 20030160) see the
    # actor's actual remaining energy.  No other ctx field is refreshed.
    ctx.actor_energy = actor.current_energy
    run_skill_timing(hot.SKILL_EFFECT_ROWS, hot.SKILL_EFFECT_RANGES[skill_id], TIMING_AFTER_MOVE, ctx)
    _run_ability_timing(actor, TIMING_AFTER_MOVE, ctx)
    ctx.poison_stacks += _unpack_skill_count(actor.element_poison_stacks, Element(skill[SKILL_ELEMENT]))
    state = apply_after_move(state, actor_side_id, actor_slot, target_side_id, target_slot, ctx)
    state = clear_barrel_after_action(state, actor_side_id, actor_slot)
    return state, dealt


def _run_ability_timing(actor: PetState, timing: int, ctx: StageCtx) -> None:
    ability_id = hot.PETS[actor.pet_id][PET_ABILITY]
    if ability_id <= 0 or ability_id >= len(hot.ABILITY_EFFECT_RANGES):
        return
    run_skill_timing(hot.ABILITY_EFFECT_ROWS, hot.ABILITY_EFFECT_RANGES[ability_id], timing, ctx)
