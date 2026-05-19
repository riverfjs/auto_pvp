"""End-of-turn mark residuals (poison damage, solar energy)."""

from __future__ import annotations

from roco.common.constants import BPS, POISON_DAMAGE_BPS
from roco.common.packing import MarkIdx, _unpack_mark
from roco.engine.common.choices import SIDE_A, SIDE_B
from roco.engine.kernel.catalog import STAT_HP
from roco.engine.kernel.residual._shared import energy_cap
from roco.engine.kernel.state import KernelState, replace_pet, replace_side, side
from roco.generated import catalog_hot as hot


def tick_marks(state: KernelState) -> KernelState:
    """Apply mark-driven residuals on the active pet for each side."""
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
            pet = pet._replace(current_energy=energy_cap(pet, pet.current_energy + solar))
        side_state = replace_pet(side_state, side_state.active, pet)
        state = replace_side(state, side_id, side_state)
    return state
