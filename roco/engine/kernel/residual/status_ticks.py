"""Status-effect application and end-of-turn ticks (burn/poison/leech)."""

from __future__ import annotations

from roco.common.constants import BPS, LEECH_DAMAGE_BPS, POISON_DAMAGE_BPS
from roco.common.enums import AbilityFlag, StatusFlag, StatusType
from roco.engine.common.choices import SIDE_A, SIDE_B
from roco.engine.kernel.model.active_buffs import effective_immunity_flags
from roco.engine.kernel.core.catalog import STAT_HP
from roco.engine.kernel.effects.damage import burn_damage, status_immune
from roco.engine.kernel.model.state import (
    KernelState,
    PetState,
    has_status,
    replace_pet,
    replace_side,
    set_status_count,
    side,
    status_stack,
    with_status,
)
from roco.generated.catalog import hot
from roco.generated.pak.buff_immunity_table import STATUS_IMMUNITY_FLAGS_BY_STATUS_TYPE


def apply_status_effect(
    pet: PetState,
    status: StatusType,
    flag: StatusFlag,
    stacks: int,
    source_side: int,
    source_slot: int,
) -> PetState:
    """Apply ``stacks`` of ``status`` to ``pet``, honouring per-status immunity.

    ``StatusType.LEECH`` ignores immunity (intended by pak) and additionally
    records the source side/slot so the leech tick knows where to siphon HP
    back to.
    """
    if stacks <= 0:
        return pet
    if status != StatusType.LEECH and status_immune(pet, flag):
        return pet
    # Active-buff immunity (Phase 5B-mini).  Pak ``BUFF_CONF[id].desc`` is
    # the source of truth for which statuses each buff blocks; the
    # StatusType→IMMUNITY_* join is generated into
    # :data:`STATUS_IMMUNITY_FLAGS_BY_STATUS_TYPE` from
    # :data:`IMMUNITY_SPECS` × :class:`StatusType`.  Unlike the
    # element-type ``status_immune`` path, this layer DOES cover leech
    # — pak 20030011 explicitly lists 寄生 in its immune list.
    buff_immunity = effective_immunity_flags(pet.active_buffs)
    if buff_immunity & STATUS_IMMUNITY_FLAGS_BY_STATUS_TYPE.get(int(status), 0):
        return pet
    pet = with_status(pet, status, stacks)
    if status == StatusType.LEECH:
        pet = pet._replace(leech_source_side=source_side, leech_source_slot=source_slot)
    return pet


def tick_leech(state: KernelState) -> KernelState:
    """Apply LEECH damage to leeched pets and refund the source pet."""
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


def tick_status(state: KernelState) -> KernelState:
    """Apply BURN/POISON tick damage and (for burn) the decay rule."""
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
            if enemy.ability_flags & int(AbilityFlag.HEAL_ON_BURN_DAMAGE):
                enemy_max = hot.PETS[enemy.pet_id][STAT_HP]
                enemy = enemy._replace(current_hp=min(enemy_max, enemy.current_hp + damage))
                enemy_side = replace_pet(enemy_side, enemy_side.active, enemy)
                state = replace_side(state, enemy_side_id, enemy_side)
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
            if enemy.ability_flags & int(AbilityFlag.HEAL_ON_POISON_DAMAGE):
                enemy_max = hot.PETS[enemy.pet_id][STAT_HP]
                enemy = enemy._replace(current_hp=min(enemy_max, enemy.current_hp + damage))
                enemy_side = replace_pet(enemy_side, enemy_side.active, enemy)
                state = replace_side(state, enemy_side_id, enemy_side)
        side_state = replace_pet(side_state, slot, pet)
        state = replace_side(state, side_id, side_state)
    return state
