"""Turn-action handlers split out of ``mechanics``.

Covers the non-move branches of a turn — focus (passing for +5 energy),
leader transform (one-shot bloodline transformation) — plus the energy
arithmetic helpers used by both ``mechanics._execute`` and the residual
phase modules.

Kept separate so ``mechanics`` can stay focused on the round-flow logic
(order/execute) and so ``residual`` can import ``energy_cap`` without
reaching back into ``mechanics``.
"""

from __future__ import annotations

from roco.common.constants import BPS, BLOODLINE_LEADER, FOCUS_ENERGY_GAIN, MAX_ENERGY
from roco.common.enums import AbilityFlag
from roco.engine.kernel.core.catalog import PET_ABILITY, STAT_HP
from roco.engine.kernel.model.state import (
    KernelState,
    PetState,
    replace_pet,
    replace_side,
    side,
)
from roco.generated.catalog import hot


def energy_cap(pet: PetState, value: int) -> int:
    """Clamp ``value`` to ``[0, MAX_ENERGY]`` unless the pet has ENERGY_NO_CAP."""
    if pet.ability_flags & int(AbilityFlag.ENERGY_NO_CAP):
        return max(0, value)
    return max(0, min(MAX_ENERGY, value))


def can_pay_hp_for_energy(pet: PetState, missing: int, pct_bps: int) -> bool:
    """True if ``pet`` has enough HP to pay ``missing`` energy at ``pct_bps``/unit."""
    if missing <= 0:
        return True
    max_hp = hot.PETS[pet.pet_id][STAT_HP]
    cost = max(1, max_hp * pct_bps // BPS) * missing
    return pet.current_hp > cost


def pay_skill_cost_with_hp(pet: PetState, cost: int, pct_bps: int) -> PetState:
    """Drain HP to cover the remaining energy cost; leaves the pet at >=1 HP."""
    missing = max(0, cost - pet.current_energy)
    max_hp = hot.PETS[pet.pet_id][STAT_HP]
    hp_cost = max(1, max_hp * pct_bps // BPS) * missing
    return pet._replace(current_hp=max(1, pet.current_hp - hp_cost), current_energy=0)


def focus(state: KernelState, side_id: int) -> KernelState:
    """``ACTION_FOCUS`` — pet skips its move to regain +5 energy."""
    # Lazy import keeps ``residual`` -> ``actions`` direction one-way.
    from roco.engine.kernel.residual import share_gains_on_side

    side_state = side(state, side_id)
    slot = side_state.active
    pet = side_state.pets[slot]
    if pet.fainted:
        return state
    before = pet.current_energy
    pet = pet._replace(current_energy=energy_cap(pet, pet.current_energy + FOCUS_ENERGY_GAIN))
    side_state = replace_pet(side_state, slot, pet)
    gained = pet.current_energy - before
    if gained > 0 and pet.ability_flags & int(AbilityFlag.SHARE_GAINS):
        side_state, rng = share_gains_on_side(side_state, slot, 0, gained, state.rng)
        state = state._replace(rng=rng)
    return replace_side(state, side_id, side_state)


def leader_transform(state: KernelState, side_id: int, slot: int) -> KernelState:
    """``ACTION_MAGIC`` for a leader-bloodline pet — one-shot form swap."""
    side_state = side(state, side_id)
    if side_state.leader_uses <= 0 or slot >= len(side_state.bloodlines):
        return state
    if side_state.bloodlines[slot] != BLOODLINE_LEADER:
        return state
    pet = side_state.pets[slot]
    if pet.fainted or pet.pet_id >= len(hot.LEADER_FORM_BY_PET):
        return state
    target_pet_id = hot.LEADER_FORM_BY_PET[pet.pet_id]
    if target_pet_id <= 0 or target_pet_id == pet.pet_id:
        return state
    old_hp = max(1, hot.PETS[pet.pet_id][STAT_HP])
    new_hp = max(1, hot.PETS[target_pet_id][STAT_HP])
    scaled_hp = max(1, min(new_hp, pet.current_hp * new_hp // old_hp))
    ability_id = hot.PETS[target_pet_id][PET_ABILITY]
    ability_flags = hot.ABILITY_FLAGS[ability_id] if ability_id < len(hot.ABILITY_FLAGS) else 0
    transformed = pet._replace(
        pet_id=target_pet_id,
        current_hp=scaled_hp,
        ability_flags=ability_flags,
    )
    side_state = replace_pet(side_state, slot, transformed)
    side_state = side_state._replace(leader_uses=side_state.leader_uses - 1)
    return replace_side(state, side_id, side_state)
