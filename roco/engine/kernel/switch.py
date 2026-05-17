"""Switch, faint, and winner lifecycle for the fixed kernel."""

from __future__ import annotations

from roco.engine.common.choices import NO_WINNER, SIDE_A, SIDE_B, WIN_A, WIN_B, WIN_DRAW
from roco.engine.common.packing import MarkIdx, _set_mark, _unpack_mark
from roco.engine.enums import AbilityFlag
from roco.engine.generated import catalog_hot as hot
from roco.engine.kernel.catalog import STAT_HP
from roco.engine.kernel.ctx import BPS
from roco.engine.kernel.state import KernelState, SideState, replace_pet, replace_side, side

POSITIVE_MARK_MASK = sum(0xF << (idx.value * 4) for idx in (
    MarkIdx.MOISTURE,
    MarkIdx.DRAGON,
    MarkIdx.MOMENTUM,
    MarkIdx.WIND,
    MarkIdx.CHARGE,
    MarkIdx.SOLAR,
    MarkIdx.ATTACK,
    MarkIdx.SLUGGISH,
))
NEGATIVE_MARK_MASK = sum(0xF << (idx.value * 4) for idx in (
    MarkIdx.SLOW,
    MarkIdx.SPIRIT,
    MarkIdx.METEOR,
    MarkIdx.POISON,
    MarkIdx.THORN,
))


def switch(state: KernelState, side_id: int, slot: int) -> KernelState:
    side_state = side(state, side_id)
    if slot < 0 or slot >= len(side_state.pets):
        return state
    if side_state.pets[slot].fainted:
        return state
    outgoing = side_state.pets[side_state.active]
    if outgoing.ability_flags & int(AbilityFlag.BARREL_ACTIVE):
        side_state = side_state._replace(barrel_pending=1)
    side_state = side_state._replace(active=slot)
    if side_state.barrel_pending:
        incoming = side_state.pets[slot]._replace(
            ability_flags=side_state.pets[slot].ability_flags | int(AbilityFlag.BARREL_ACTIVE)
        )
        side_state = replace_pet(side_state, slot, incoming)._replace(barrel_pending=0)
    side_state = apply_switch_in_marks(side_state, slot)
    return replace_side(state, side_id, side_state)


def apply_mark_delta(current: int, delta: int) -> int:
    marks = current
    for idx in MarkIdx:
        stacks = _unpack_mark(delta, idx)
        if stacks <= 0:
            continue
        keep = 0xF << (idx.value * 4)
        marks &= ~(same_polarity_mask(idx) & ~keep)
        marks = _set_mark(marks, idx, min(15, _unpack_mark(marks, idx) + stacks))
    return marks


def same_polarity_mask(idx: MarkIdx) -> int:
    return POSITIVE_MARK_MASK if POSITIVE_MARK_MASK & (0xF << (idx.value * 4)) else NEGATIVE_MARK_MASK


def apply_switch_in_marks(side_state: SideState, slot: int) -> SideState:
    pet = side_state.pets[slot]
    thorn = _unpack_mark(side_state.marks, MarkIdx.THORN)
    spirit = _unpack_mark(side_state.marks, MarkIdx.SPIRIT)
    if thorn > 0:
        pet = pet._replace(current_hp=max(0, pet.current_hp - hot.PETS[pet.pet_id][STAT_HP] * thorn * 600 // BPS))
    if spirit > 0:
        pet = pet._replace(current_energy=max(0, pet.current_energy - spirit))
    return replace_pet(side_state, slot, pet)


def clear_barrel_after_action(state: KernelState, side_id: int, slot: int) -> KernelState:
    side_state = side(state, side_id)
    pet = side_state.pets[slot]
    if pet.ability_flags & int(AbilityFlag.BARREL_ACTIVE):
        pet = pet._replace(ability_flags=pet.ability_flags & ~int(AbilityFlag.BARREL_ACTIVE))
        side_state = replace_pet(side_state, slot, pet)
        state = replace_side(state, side_id, side_state)
    return state


def mark_zero_hp_fainted(state: KernelState) -> KernelState:
    for side_id in (SIDE_A, SIDE_B):
        side_state = side(state, side_id)
        for slot, pet in enumerate(side_state.pets):
            if pet.current_hp <= 0 and not pet.fainted:
                state = faint_pet(state, side_id, slot)
                side_state = side(state, side_id)
    return state


def faint_pet(
    state: KernelState,
    side_id: int,
    slot: int,
    killer_side_id: int = -1,
    killer_slot: int = -1,
) -> KernelState:
    side_state = side(state, side_id)
    pet = side_state.pets[slot]
    if pet.fainted:
        return state
    magic_cost = 0 if pet.ability_flags & int(AbilityFlag.FAKE_DEATH) else 1
    pet = pet._replace(current_hp=0, fainted=1)
    if pet.cute > 0 and killer_side_id >= 0:
        killer_side = side(state, killer_side_id)
        if 0 <= killer_slot < len(killer_side.pets):
            killer = killer_side.pets[killer_slot]
            if not killer.fainted:
                killer = killer._replace(cute=killer.cute + pet.cute)
                killer_side = replace_pet(killer_side, killer_slot, killer)
                state = replace_side(state, killer_side_id, killer_side)
                pet = pet._replace(cute=0)
                side_state = side(state, side_id)
    side_state = replace_pet(side_state, slot, pet)._replace(magic=max(0, side_state.magic - magic_cost))
    if slot == side_state.active:
        for idx, candidate in enumerate(side_state.pets):
            if idx != slot and not candidate.fainted:
                side_state = side_state._replace(active=idx)
                side_state = apply_switch_in_marks(side_state, idx)
                break
    return replace_side(state, side_id, side_state)


def check_winner(state: KernelState) -> KernelState:
    alive_a = has_alive(state.side_a)
    alive_b = has_alive(state.side_b)
    winner = NO_WINNER
    if not alive_a and not alive_b:
        winner = WIN_DRAW
    elif not alive_a:
        winner = WIN_B
    elif not alive_b:
        winner = WIN_A
    return state._replace(winner=winner)


def has_alive(side_state: SideState) -> bool:
    for pet in side_state.pets:
        if not pet.fainted:
            return True
    return False
