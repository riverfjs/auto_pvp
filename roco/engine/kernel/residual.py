"""After-move and turn-end residual resolution."""

from __future__ import annotations

from roco.config.constants import MAX_ENERGY
from roco.engine.common.choices import SIDE_A, SIDE_B
from roco.engine.common.packing import MarkIdx, _unpack_mark
from roco.engine.enums import AbilityFlag, StatusFlag, StatusType, WeatherType
from roco.engine.generated import catalog_hot as hot
from roco.engine.kernel.catalog import STAT_HP
from roco.engine.kernel.ctx import BPS, StageCtx
from roco.engine.kernel.damage import (
    LEECH_DAMAGE_BPS,
    POISON_DAMAGE_BPS,
    burn_damage,
    sandstorm_immune,
    status_immune,
)
from roco.engine.kernel.state import (
    KernelState,
    PetState,
    has_status,
    pack_weather,
    replace_pet,
    replace_side,
    set_status_count,
    side,
    status_stack,
    weather_turns,
    weather_type,
    with_status,
)
from roco.engine.kernel.switch import apply_mark_delta, mark_zero_hp_fainted


def apply_after_move(
    state: KernelState,
    actor_side_id: int,
    actor_slot: int,
    target_side_id: int,
    target_slot: int,
    ctx: StageCtx,
) -> KernelState:
    if ctx.weather:
        state = state._replace(weather=pack_weather(ctx.weather, ctx.weather_turns))
    actor_side = side(state, actor_side_id)
    target_side = side(state, target_side_id)
    if ctx.clear_self_marks:
        actor_side = actor_side._replace(marks=0)
    if ctx.clear_enemy_marks:
        target_side = target_side._replace(marks=0)
    if ctx.mark_self:
        actor_side = actor_side._replace(marks=apply_mark_delta(actor_side.marks, ctx.mark_self))
    if ctx.mark_enemy:
        target_side = target_side._replace(marks=apply_mark_delta(target_side.marks, ctx.mark_enemy))
    state = replace_side(state, actor_side_id, actor_side)
    state = replace_side(state, target_side_id, target_side)
    target_side = side(state, target_side_id)
    target = target_side.pets[target_slot]
    target = apply_status_effect(target, StatusType.BURN, StatusFlag.BURN, ctx.burn_stacks, actor_side_id, actor_slot)
    target = apply_status_effect(target, StatusType.POISON, StatusFlag.POISON, ctx.poison_stacks, actor_side_id, actor_slot)
    target = apply_status_effect(target, StatusType.FREEZE, StatusFlag.FREEZE, ctx.freeze_stacks, actor_side_id, actor_slot)
    target = apply_status_effect(target, StatusType.LEECH, StatusFlag.LEECH, ctx.leech_stacks, actor_side_id, actor_slot)
    target_side = replace_pet(target_side, target_slot, target)
    return replace_side(state, target_side_id, target_side)


def apply_status_effect(
    pet: PetState,
    status: StatusType,
    flag: StatusFlag,
    stacks: int,
    source_side: int,
    source_slot: int,
) -> PetState:
    if stacks <= 0:
        return pet
    if status != StatusType.LEECH and status_immune(pet, flag):
        return pet
    pet = with_status(pet, status, stacks)
    if status == StatusType.LEECH:
        pet = pet._replace(leech_source_side=source_side, leech_source_slot=source_slot)
    return pet


def end_turn(state: KernelState) -> KernelState:
    state = tick_leech(state)
    state = tick_marks(state)
    state = tick_weather(state)
    state = tick_status(state)
    return mark_zero_hp_fainted(state)


def tick_leech(state: KernelState) -> KernelState:
    for side_id in (SIDE_A, SIDE_B):
        side_state = side(state, side_id)
        slot = side_state.active
        pet = side_state.pets[slot]
        stacks = status_stack(pet, StatusType.LEECH)
        if pet.fainted or stacks <= 0 or pet.leech_source_side < 0:
            continue
        damage = hot.PETS[pet.pet_id][STAT_HP] * stacks * LEECH_DAMAGE_BPS // BPS
        pet = pet._replace(current_hp=max(0, pet.current_hp - damage))
        side_state = replace_pet(side_state, slot, pet)
        state = replace_side(state, side_id, side_state)
        source_side = side(state, pet.leech_source_side)
        source_slot = pet.leech_source_slot
        if 0 <= source_slot < len(source_side.pets):
            source = source_side.pets[source_slot]
            if not source.fainted:
                max_hp = hot.PETS[source.pet_id][STAT_HP]
                source = source._replace(current_hp=min(max_hp, source.current_hp + damage))
                source_side = replace_pet(source_side, source_slot, source)
                state = replace_side(state, pet.leech_source_side, source_side)
    return state


def tick_marks(state: KernelState) -> KernelState:
    for side_id in (SIDE_A, SIDE_B):
        side_state = side(state, side_id)
        pet = side_state.pets[side_state.active]
        if pet.fainted:
            continue
        poison = _unpack_mark(side_state.marks, MarkIdx.POISON)
        solar = _unpack_mark(side_state.marks, MarkIdx.SOLAR)
        if poison > 0:
            damage = hot.PETS[pet.pet_id][STAT_HP] * poison * POISON_DAMAGE_BPS // BPS
            pet = pet._replace(current_hp=max(0, pet.current_hp - damage))
        if solar > 0:
            pet = pet._replace(current_energy=min(MAX_ENERGY, pet.current_energy + solar))
        side_state = replace_pet(side_state, side_state.active, pet)
        state = replace_side(state, side_id, side_state)
    return state


def tick_weather(state: KernelState) -> KernelState:
    current = weather_type(state.weather)
    turns = weather_turns(state.weather)
    if current == WeatherType.NONE.value:
        return state
    for side_id in (SIDE_A, SIDE_B):
        side_state = side(state, side_id)
        slot = side_state.active
        pet = side_state.pets[slot]
        if pet.fainted:
            continue
        if current == WeatherType.SANDSTORM.value and not sandstorm_immune(pet):
            damage = hot.PETS[pet.pet_id][STAT_HP] // 16
            pet = pet._replace(current_hp=max(0, pet.current_hp - damage))
        elif current == WeatherType.SNOW.value:
            max_hp = hot.PETS[pet.pet_id][STAT_HP]
            pet = pet._replace(frostbite=pet.frostbite + max_hp // 12)
            pet = with_status(pet, StatusType.FREEZE, 2)
        side_state = replace_pet(side_state, slot, pet)
        state = replace_side(state, side_id, side_state)
    if turns > 0:
        turns -= 1
        state = state._replace(weather=pack_weather(current, turns) if turns > 0 else 0)
    return state


def tick_status(state: KernelState) -> KernelState:
    for side_id, enemy_side_id in ((SIDE_A, SIDE_B), (SIDE_B, SIDE_A)):
        side_state = side(state, side_id)
        enemy_side = side(state, enemy_side_id)
        enemy = enemy_side.pets[enemy_side.active]
        slot = side_state.active
        pet = side_state.pets[slot]
        if pet.fainted:
            continue
        if has_status(pet, StatusFlag.BURN):
            stacks = status_stack(pet, StatusType.BURN)
            damage = burn_damage(pet, stacks)
            pet = pet._replace(current_hp=max(0, pet.current_hp - damage))
            if enemy.ability_flags & int(AbilityFlag.BURN_NO_DECAY):
                stacks += max(1, stacks // 2)
            else:
                stacks = max(0, stacks - max(1, stacks // 2))
            pet = set_status_count(pet, StatusType.BURN, stacks)
        if has_status(pet, StatusFlag.POISON):
            stacks = status_stack(pet, StatusType.POISON)
            damage = hot.PETS[pet.pet_id][STAT_HP] * stacks * POISON_DAMAGE_BPS // BPS
            if enemy.ability_flags & int(AbilityFlag.EXTRA_POISON_TICK):
                damage *= 2
            pet = pet._replace(current_hp=max(0, pet.current_hp - damage))
        side_state = replace_pet(side_state, slot, pet)
        state = replace_side(state, side_id, side_state)
    return state
