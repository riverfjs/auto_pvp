"""Switch, faint, and winner lifecycle for the fixed kernel."""

from __future__ import annotations

from roco.engine.common.choices import NO_WINNER, SIDE_A, SIDE_B, WIN_A, WIN_B, WIN_DRAW
from roco.common.packing import (
    MarkIdx,
    _add_to_positive_buff_lanes,
    _inc_skill_count,
    _merge_buff_delta,
    _merge_element_nibbles,
    _merge_element_u8,
    _merge_element_u8_max,
    _set_mark,
    _unpack_mark,
)
from roco.common.constants import BPS, MAX_ENERGY, SPIRIT_ENTRY_ENERGY_LOSS, THORN_ENTRY_DAMAGE_BPS
from roco.common.enums import AbilityFlag, Element
from roco.generated import catalog_hot as hot
from roco.engine.kernel.catalog import ELEMENT_BUG, PET_ABILITY, PET_PRIMARY, PET_SECONDARY, SKILL_ELEMENT, STAT_HP
from roco.engine.kernel.ctx import StageCtx
from roco.engine.kernel.op_rows import TIMING_HOOK_ENEMY_SWITCH, TIMING_PAK_SDT, TIMING_HOOK_SWITCH_OUT
from roco.engine.kernel.ops import run_skill_timing
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
    outgoing_slot = side_state.active
    outgoing = side_state.pets[outgoing_slot]
    if outgoing.ability_flags & int(AbilityFlag.BARREL_ACTIVE):
        side_state = side_state._replace(barrel_pending=1)
    copy_mods = bool(outgoing.ability_flags & int(AbilityFlag.COPY_SWITCH_STATE))
    side_state = side_state._replace(
        active=slot,
        switch_count=min(255, side_state.switch_count + (1 if slot != outgoing_slot else 0)),
    )
    side_state = apply_switch_out_ability(side_state, outgoing_slot, slot)
    if copy_mods:
        incoming = side_state.pets[slot]._replace(buff_stages=outgoing.buff_stages)
        side_state = replace_pet(side_state, slot, incoming)
    if side_state.barrel_pending:
        incoming = side_state.pets[slot]._replace(
            ability_flags=side_state.pets[slot].ability_flags | int(AbilityFlag.BARREL_ACTIVE)
        )
        side_state = replace_pet(side_state, slot, incoming)._replace(barrel_pending=0)
    enemy_side = SIDE_B if side_id == SIDE_A else SIDE_A
    side_state = apply_switch_in_marks(side_state, slot)
    side_state = apply_switch_in_ability(side_state, slot, side(state, enemy_side))
    state = replace_side(state, side_id, side_state)
    return apply_enemy_switch_reactions(state, enemy_side, side_id, slot)


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


def apply_mark_delta_no_replace(current: int, delta: int) -> int:
    marks = current
    for idx in MarkIdx:
        stacks = _unpack_mark(delta, idx)
        if stacks > 0:
            marks = _set_mark(marks, idx, min(15, _unpack_mark(marks, idx) + stacks))
    return marks


def same_polarity_mask(idx: MarkIdx) -> int:
    return POSITIVE_MARK_MASK if POSITIVE_MARK_MASK & (0xF << (idx.value * 4)) else NEGATIVE_MARK_MASK


def apply_switch_in_marks(side_state: SideState, slot: int) -> SideState:
    pet = side_state.pets[slot]
    thorn = _unpack_mark(side_state.marks, MarkIdx.THORN)
    spirit = _unpack_mark(side_state.marks, MarkIdx.SPIRIT)
    if thorn > 0:
        pet = pet._replace(current_hp=max(0, pet.current_hp - hot.PETS[pet.pet_id][STAT_HP] * thorn * THORN_ENTRY_DAMAGE_BPS // BPS))
    if spirit > 0:
        pet = pet._replace(current_energy=max(0, pet.current_energy - spirit * SPIRIT_ENTRY_ENERGY_LOSS))
    return replace_pet(side_state, slot, pet)


def apply_switch_in_ability(side_state: SideState, slot: int, enemy_side: SideState | None = None) -> SideState:
    pet = side_state.pets[slot]
    ability_id = hot.PETS[pet.pet_id][PET_ABILITY]
    if ability_id <= 0 or ability_id >= len(hot.ABILITY_EFFECT_RANGES):
        return side_state
    ctx = StageCtx()
    ctx.reset(0, slot, 0, slot, 0)
    ctx.actor_energy = pet.current_energy
    if enemy_side is not None:
        ctx.target_energy = enemy_side.pets[enemy_side.active].current_energy
    ctx.side_skill_counts = side_state.skill_counts
    ctx.side_counter_count = side_state.counter_count
    ctx.side_status_skill_count = side_state.status_skill_count
    ctx.side_defense_skill_count = side_state.defense_skill_count
    ctx.side_skill_dam_type_counts = side_state.skill_dam_type_counts
    if enemy_side is not None:
        ctx.enemy_skill_dam_type_counts = enemy_side.skill_dam_type_counts
        ctx.enemy_switch_count = enemy_side.switch_count
    equipped_counts = 0
    for skill_id in side_state.moves[slot]:
        if skill_id > 0:
            equipped_counts = _inc_skill_count(equipped_counts, Element(hot.SKILLS[skill_id][SKILL_ELEMENT]))
    ctx.side_equipped_skill_counts = equipped_counts
    element_counts = 0
    for idx, other in enumerate(side_state.pets):
        if idx == slot or other.fainted:
            continue
        row = hot.PETS[other.pet_id]
        element_counts = _inc_skill_count(element_counts, Element(row[PET_PRIMARY]))
        if row[PET_SECONDARY] >= 0 and row[PET_SECONDARY] != row[PET_PRIMARY]:
            element_counts = _inc_skill_count(element_counts, Element(row[PET_SECONDARY]))
    ctx.side_element_counts = element_counts
    ctx.side_fainted_count = sum(1 for idx, other in enumerate(side_state.pets) if idx != slot and other.fainted)
    ctx.side_bench_cute = sum(other.cute for idx, other in enumerate(side_state.pets) if idx != slot and not other.fainted)
    ctx.side_bug_count = sum(
        1 for idx, other in enumerate(side_state.pets)
        if idx != slot and not other.fainted and hot.PETS[other.pet_id][PET_PRIMARY] == ELEMENT_BUG
    )
    run_skill_timing(hot.ABILITY_EFFECT_ROWS, hot.ABILITY_EFFECT_RANGES[ability_id], TIMING_PAK_SDT, ctx)
    if ctx.entry_self_damage_bps:
        pet = pet._replace(current_hp=max(1, pet.current_hp - pet.current_hp * ctx.entry_self_damage_bps // BPS))
    if ctx.drain_bps:
        pet = pet._replace(lifedrain_bps=max(pet.lifedrain_bps, ctx.drain_bps))
    if ctx.entry_cost_delta:
        pet = pet._replace(global_cost_delta=max(-15, min(15, pet.global_cost_delta + ctx.entry_cost_delta)))
    if ctx.entry_power_bonus:
        pet = pet._replace(global_power_bonus=max(-255, min(255, pet.global_power_bonus + ctx.entry_power_bonus)))
    if ctx.entry_element_power_flat:
        pet = pet._replace(element_power_flat=_merge_element_u8(pet.element_power_flat, ctx.entry_element_power_flat))
    if ctx.entry_element_power_bps:
        pet = pet._replace(element_power_bps=_merge_element_u8(pet.element_power_bps, ctx.entry_element_power_bps))
    if ctx.entry_element_cost_reduce:
        pet = pet._replace(element_cost_reduce=_merge_element_nibbles(pet.element_cost_reduce, ctx.entry_element_cost_reduce))
    if ctx.entry_element_poison_stacks:
        pet = pet._replace(
            element_poison_stacks=_merge_element_nibbles(
                pet.element_poison_stacks,
                ctx.entry_element_poison_stacks,
            )
        )
    if ctx.entry_element_damage_reduce:
        pet = pet._replace(
            element_damage_reduce=_merge_element_u8_max(
                pet.element_damage_reduce,
                ctx.entry_element_damage_reduce,
            )
        )
    if ctx.entry_element_damage_resist:
        pet = pet._replace(
            element_damage_resist=pet.element_damage_resist | ctx.entry_element_damage_resist
        )
    if ctx.mirror_enemy_buffs and enemy_side is not None:
        pet = pet._replace(buff_stages=enemy_side.pets[enemy_side.active].buff_stages)
    if ctx.self_buff:
        self_buff = ctx.self_buff
        if pet.ability_flags & int(AbilityFlag.BUFF_EXTRA_LAYERS):
            self_buff = _add_to_positive_buff_lanes(self_buff, 2000)
        pet = pet._replace(buff_stages=_merge_buff_delta(pet.buff_stages, self_buff))
    if ctx.heal_energy:
        pet = pet._replace(current_energy=_energy_cap(pet, pet.current_energy + ctx.heal_energy))
    return replace_pet(side_state, slot, pet)


def apply_switch_out_ability(side_state: SideState, outgoing_slot: int, incoming_slot: int) -> SideState:
    outgoing = side_state.pets[outgoing_slot]
    incoming = side_state.pets[incoming_slot]
    ability_id = hot.PETS[outgoing.pet_id][PET_ABILITY]
    if ability_id <= 0 or ability_id >= len(hot.ABILITY_EFFECT_RANGES):
        return side_state
    ctx = StageCtx()
    ctx.reset(0, outgoing_slot, 0, incoming_slot, 0)
    run_skill_timing(hot.ABILITY_EFFECT_ROWS, hot.ABILITY_EFFECT_RANGES[ability_id], TIMING_HOOK_SWITCH_OUT, ctx)
    if ctx.heal_hp_bps:
        max_hp = hot.PETS[incoming.pet_id][STAT_HP]
        incoming = incoming._replace(current_hp=min(max_hp, incoming.current_hp + max_hp * ctx.heal_hp_bps // BPS))
    if ctx.heal_energy:
        incoming = incoming._replace(current_energy=_energy_cap(incoming, incoming.current_energy + ctx.heal_energy))
    return replace_pet(side_state, incoming_slot, incoming)


def apply_enemy_switch_reactions(state: KernelState, reactor_side_id: int, switched_side_id: int, incoming_slot: int) -> KernelState:
    reactor_side = side(state, reactor_side_id)
    switched_side = side(state, switched_side_id)
    reactor_slot = reactor_side.active
    reactor = reactor_side.pets[reactor_slot]
    incoming = switched_side.pets[incoming_slot]
    ability_id = hot.PETS[reactor.pet_id][PET_ABILITY]
    if reactor.fainted or ability_id <= 0 or ability_id >= len(hot.ABILITY_EFFECT_RANGES):
        return state
    ctx = StageCtx()
    ctx.reset(reactor_side_id, reactor_slot, switched_side_id, incoming_slot, 0)
    run_skill_timing(hot.ABILITY_EFFECT_ROWS, hot.ABILITY_EFFECT_RANGES[ability_id], TIMING_HOOK_ENEMY_SWITCH, ctx)
    if ctx.entry_cost_delta:
        reactor = reactor._replace(global_cost_delta=max(-15, min(15, reactor.global_cost_delta + ctx.entry_cost_delta)))
        reactor_side = replace_pet(reactor_side, reactor_slot, reactor)
        state = replace_side(state, reactor_side_id, reactor_side)
    if ctx.enemy_lose_energy:
        incoming = incoming._replace(current_energy=max(0, incoming.current_energy - ctx.enemy_lose_energy))
        switched_side = replace_pet(switched_side, incoming_slot, incoming)
        state = replace_side(state, switched_side_id, switched_side)
    return state


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
    fake_death = bool(pet.ability_flags & int(AbilityFlag.FAKE_DEATH))
    magic_cost = 0 if fake_death else 1
    if not fake_death and pet.ability_flags & int(AbilityFlag.KILL_MP_PENALTY):
        magic_cost += 1
    if not fake_death and killer_side_id >= 0 and killer_slot >= 0:
        killer_side = side(state, killer_side_id)
        if killer_slot < len(killer_side.pets) and killer_side.pets[killer_slot].ability_flags & int(AbilityFlag.KILL_MP_PENALTY):
            magic_cost += 1
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
    side_state = replace_pet(side_state, slot, pet)._replace(side_lives=max(0, side_state.side_lives - magic_cost))
    if slot == side_state.active:
        for idx, candidate in enumerate(side_state.pets):
            if idx != slot and not candidate.fainted:
                side_state = side_state._replace(active=idx)
                side_state = apply_switch_out_ability(side_state, slot, idx)
                if pet.ability_flags & int(AbilityFlag.COPY_SWITCH_STATE):
                    candidate = side_state.pets[idx]._replace(buff_stages=pet.buff_stages)
                    side_state = replace_pet(side_state, idx, candidate)
                side_state = apply_switch_in_marks(side_state, idx)
                enemy_side = SIDE_B if side_id == SIDE_A else SIDE_A
                side_state = apply_switch_in_ability(side_state, idx, side(state, enemy_side))
                state = replace_side(state, side_id, side_state)
                return apply_enemy_switch_reactions(state, enemy_side, side_id, idx)
                break
    return replace_side(state, side_id, side_state)


def check_winner(state: KernelState) -> KernelState:
    alive_a = has_alive(state.side_a) and state.side_a.side_lives > 0
    alive_b = has_alive(state.side_b) and state.side_b.side_lives > 0
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


def _energy_cap(pet, value: int) -> int:
    if pet.ability_flags & int(AbilityFlag.ENERGY_NO_CAP):
        return max(0, value)
    return max(0, min(MAX_ENERGY, value))
