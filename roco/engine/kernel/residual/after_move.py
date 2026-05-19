"""``apply_after_move`` — fold ``StageCtx`` deltas back into ``KernelState``.

This is the bulk of post-move resolution: weather updates, mark replacement,
buff/debuff merging, cleanse, heal/drain/energy, cute transfers, form
transforms, status application, and force-switches.  Each ``ctx.*`` field
maps to a small conditional block — keep them next to each other so the
sequence is easy to read.
"""

from __future__ import annotations

from roco.common.constants import BPS, CUTE_MAX_STACKS
from roco.common.enums import AbilityFlag, StatusFlag, StatusType
from roco.common.packing import (
    DevotionIdx,
    MarkIdx,
    _add_to_negative_buff_lanes,
    _add_to_positive_buff_lanes,
    _clear_buff_lanes,
    _merge_buff_delta,
    _set_cooldown,
    _set_devotion,
    _unpack_devotion,
    _unpack_mark,
)
from roco.engine.common.rng import next_rng
from roco.engine.kernel.catalog import PET_ABILITY, STAT_HP
from roco.engine.kernel.ctx import StageCtx
from roco.engine.kernel.residual._shared import energy_cap
from roco.engine.kernel.residual.status_ticks import apply_status_effect
from roco.engine.kernel.state import (
    KernelState,
    PetState,
    pack_cost_mod,
    replace_pet,
    replace_side,
    side,
)
from roco.engine.kernel.switch import (
    apply_mark_delta,
    apply_mark_delta_no_replace,
    switch as switch_state,
)
from roco.generated import catalog_hot as hot


def apply_after_move(
    state: KernelState,
    actor_side_id: int,
    actor_slot: int,
    target_side_id: int,
    target_slot: int,
    ctx: StageCtx,
) -> KernelState:
    if ctx.weather:
        from roco.engine.kernel.state import pack_weather
        state = state._replace(weather=pack_weather(ctx.weather, ctx.weather_turns))
    actor_side = side(state, actor_side_id)
    target_side = side(state, target_side_id)
    actor = actor_side.pets[actor_slot]
    if ctx.clear_self_marks:
        # Count the stacks we're about to drop so TURN_END ops like
        # ``op_dispel_marks_to_burn`` can multiply by them.  Both
        # self-clears and enemy-clears credit the *actor* side so two
        # simultaneous dispellers don't poach each other's count.
        dropped = _sum_mark_stacks(actor_side.marks)
        if dropped:
            state = _credit_dispel(state, actor_side_id, dropped)
        actor_side = actor_side._replace(marks=0)
    if ctx.clear_enemy_marks:
        dropped = _sum_mark_stacks(target_side.marks)
        if dropped:
            state = _credit_dispel(state, actor_side_id, dropped)
        target_side = target_side._replace(marks=0)
    mark_apply = apply_mark_delta_no_replace if actor.ability_flags & int(AbilityFlag.MARK_STACK_NO_REPLACE) else apply_mark_delta
    if ctx.mark_self:
        actor_side = actor_side._replace(marks=mark_apply(actor_side.marks, ctx.mark_self))
    if ctx.mark_enemy:
        target_side = target_side._replace(marks=mark_apply(target_side.marks, ctx.mark_enemy))
    if ctx.enemy_cost_delta and ctx.enemy_cost_turns:
        target_side = target_side._replace(cost_mods=pack_cost_mod(
            ctx.enemy_cost_delta,
            ctx.enemy_cost_turns,
            ctx.enemy_cost_scope,
            ctx.target_skill_slot,
        ))
    if ctx.devotion_random:
        actor_side = actor_side._replace(devotion=_add_devotion(actor_side.devotion, DevotionIdx.JIAMEI, ctx.devotion_random))
    state = replace_side(state, actor_side_id, actor_side)
    state = replace_side(state, target_side_id, target_side)
    actor_side = side(state, actor_side_id)
    target_side = side(state, target_side_id)
    actor = actor_side.pets[actor_slot]
    target = target_side.pets[target_slot]
    if ctx.clear_self_buffs or ctx.clear_self_debuffs:
        actor = actor._replace(buff_stages=_clear_buff_lanes(
            actor.buff_stages,
            positive=bool(ctx.clear_self_buffs),
            negative=bool(ctx.clear_self_debuffs),
        ))
    if ctx.clear_enemy_buffs or ctx.clear_enemy_debuffs:
        target = target._replace(buff_stages=_clear_buff_lanes(
            target.buff_stages,
            positive=bool(ctx.clear_enemy_buffs),
            negative=bool(ctx.clear_enemy_debuffs),
        ))
    if ctx.cleanse_self:
        actor = actor._replace(status_flags=0, status_counts=0, frostbite=0, leech_source_side=-1, leech_source_slot=-1)
    if ctx.cleanse_enemy:
        target = target._replace(status_flags=0, status_counts=0, frostbite=0, leech_source_side=-1, leech_source_slot=-1)
    if ctx.self_buff:
        self_buff = ctx.self_buff
        if actor.ability_flags & int(AbilityFlag.BUFF_EXTRA_LAYERS):
            self_buff = _add_to_positive_buff_lanes(self_buff, 2000)
        actor = actor._replace(buff_stages=_merge_buff_delta(actor.buff_stages, self_buff))
    if ctx.enemy_buff:
        target = target._replace(buff_stages=_merge_buff_delta(target.buff_stages, ctx.enemy_buff))
    if ctx.debuff_extra_layers:
        target = target._replace(buff_stages=_add_to_negative_buff_lanes(target.buff_stages, ctx.debuff_extra_layers))
    if ctx.swap_mods:
        actor_buff = actor.buff_stages
        actor = actor._replace(buff_stages=target.buff_stages)
        target = target._replace(buff_stages=actor_buff)
    if ctx.exchange_hp_ratio:
        actor_max = hot.PETS[actor.pet_id][STAT_HP]
        target_max = hot.PETS[target.pet_id][STAT_HP]
        actor_hp = max(1, min(actor_max, target.current_hp * actor_max // max(1, target_max)))
        target_hp = max(1, min(target_max, actor.current_hp * target_max // max(1, actor_max)))
        actor = actor._replace(current_hp=actor_hp)
        target = target._replace(current_hp=target_hp)
    if ctx.cute_transfer:
        target = target._replace(cute=min(CUTE_MAX_STACKS, target.cute + actor.cute))
        actor = actor._replace(cute=0)
    if ctx.cute_self:
        actor = actor._replace(cute=_cute_after_delta(actor.cute, ctx.cute_self))
    if ctx.cute_enemy:
        target = target._replace(cute=_cute_after_delta(target.cute, ctx.cute_enemy))
    if ctx.enemy_anti_heal:
        target = target._replace(anti_heal_multiplier=ctx.enemy_anti_heal)
    hp_gain = 0
    energy_gain = 0
    if ctx.heal_hp_bps:
        max_hp = hot.PETS[actor.pet_id][STAT_HP]
        before = actor.current_hp
        actor = _apply_heal_hp(actor, max_hp * ctx.heal_hp_bps // BPS)
        hp_gain += max(0, actor.current_hp - before)
    drain_bps = max(ctx.drain_bps, actor.lifedrain_bps)
    if drain_bps and ctx.damage_dealt:
        before = actor.current_hp
        actor = _apply_heal_hp(actor, ctx.damage_dealt * drain_bps // BPS)
        hp_gain += max(0, actor.current_hp - before)
    if ctx.heal_energy:
        before = actor.current_energy
        actor = actor._replace(current_energy=energy_cap(actor, actor.current_energy + ctx.heal_energy))
        energy_gain += max(0, actor.current_energy - before)
    if ctx.enemy_lose_energy:
        target = target._replace(current_energy=max(0, target.current_energy - ctx.enemy_lose_energy))
    if ctx.steal_energy:
        stolen = min(target.current_energy, ctx.steal_energy)
        target = target._replace(current_energy=target.current_energy - stolen)
        before = actor.current_energy
        actor = actor._replace(current_energy=energy_cap(actor, actor.current_energy + stolen))
        energy_gain += max(0, actor.current_energy - before)
    if energy_gain and actor.ability_flags & int(AbilityFlag.HEAL_HP_PER_ENERGY_GAIN):
        max_hp = hot.PETS[actor.pet_id][STAT_HP]
        before = actor.current_hp
        actor = _apply_heal_hp(actor, max_hp * energy_gain * 500 // BPS)
        hp_gain += max(0, actor.current_hp - before)
    if ctx.priority_next:
        actor = actor._replace(priority_boost=min(15, actor.priority_boost + ctx.priority_next))
    if ctx.enemy_hit_delta:
        target = target._replace(hit_delta=max(-15, min(15, target.hit_delta + ctx.enemy_hit_delta)))
    if ctx.enemy_cooldown_turns and ctx.target_skill_slot >= 0:
        target = target._replace(cooldowns=_set_cooldown(target.cooldowns, ctx.target_skill_slot, ctx.enemy_cooldown_turns))
    if ctx.actor_self_cooldown_turns and ctx.skill_slot >= 0:
        actor = actor._replace(cooldowns=_set_cooldown(actor.cooldowns, ctx.skill_slot, ctx.actor_self_cooldown_turns))
    if ctx.counter_damage and ctx.damage_dealt:
        actor = actor._replace(current_hp=max(0, actor.current_hp - ctx.counter_damage))
    if ctx.form_transform:
        actor = _form_transform(actor, bool(ctx.form_transform_heal))
    actor_side = replace_pet(actor_side, actor_slot, actor)
    if (hp_gain or energy_gain) and actor.ability_flags & int(AbilityFlag.SHARE_GAINS):
        actor_side, rng = share_gains_on_side(actor_side, actor_slot, hp_gain, energy_gain, state.rng)
        state = state._replace(rng=rng)
    target_side = replace_pet(target_side, target_slot, target)
    if ctx.swap_moves:
        actor_moves = actor_side.moves[actor_slot]
        target_moves = target_side.moves[target_slot]
        actor_side = _replace_moves(actor_side, actor_slot, target_moves)
        target_side = _replace_moves(target_side, target_slot, actor_moves)
    state = replace_side(replace_side(state, actor_side_id, actor_side), target_side_id, target_side)
    if ctx.consume_enemy_marks_heal_bps:
        state = _consume_enemy_marks_heal(state, actor_side_id, actor_slot, target_side_id, ctx.consume_enemy_marks_heal_bps)
    target_side = side(state, target_side_id)
    target = target_side.pets[target_slot]
    target = apply_status_effect(target, StatusType.BURN, StatusFlag.BURN, ctx.burn_stacks, actor_side_id, actor_slot)
    target = apply_status_effect(target, StatusType.POISON, StatusFlag.POISON, ctx.poison_stacks, actor_side_id, actor_slot)
    freeze_stacks = ctx.freeze_stacks
    if freeze_stacks and actor.ability_flags & int(AbilityFlag.EXTRA_FREEZE_ON_FREEZE):
        freeze_stacks += ctx.freeze_stacks
    target = apply_status_effect(target, StatusType.FREEZE, StatusFlag.FREEZE, freeze_stacks, actor_side_id, actor_slot)
    target = apply_status_effect(target, StatusType.LEECH, StatusFlag.LEECH, ctx.leech_stacks, actor_side_id, actor_slot)
    target_side = replace_pet(target_side, target_slot, target)
    state = replace_side(state, target_side_id, target_side)
    if ctx.force_switch:
        state = _auto_switch(state, actor_side_id)
    if ctx.force_enemy_switch:
        state = _auto_switch(state, target_side_id)
    return state


def _sum_mark_stacks(marks: int) -> int:
    total = 0
    for idx in MarkIdx:
        total += _unpack_mark(marks, idx)
    return total


def _credit_dispel(state: KernelState, actor_side_id: int, dropped: int) -> KernelState:
    """Add ``dropped`` stacks to the actor's per-side dispel tally."""
    from roco.engine.common.choices import SIDE_A
    if actor_side_id == SIDE_A:
        return state._replace(marks_dispelled_a=state.marks_dispelled_a + dropped)
    return state._replace(marks_dispelled_b=state.marks_dispelled_b + dropped)


def _cute_after_delta(current: int, delta: int) -> int:
    if delta <= -255:
        return 0
    new_val = current + delta
    return max(0, min(CUTE_MAX_STACKS, new_val))


def _apply_heal_hp(pet: PetState, amount: int) -> PetState:
    max_hp = hot.PETS[pet.pet_id][STAT_HP]
    if amount <= 0:
        return pet
    if pet.anti_heal_multiplier:
        return pet._replace(current_hp=max(0, pet.current_hp - amount * pet.anti_heal_multiplier))
    return pet._replace(current_hp=min(max_hp, pet.current_hp + amount))


def _replace_moves(side_state, slot: int, moves: tuple[int, int, int, int]):
    return side_state._replace(moves=side_state.moves[:slot] + (moves,) + side_state.moves[slot + 1:])


def _consume_enemy_marks_heal(
    state: KernelState,
    actor_side_id: int,
    actor_slot: int,
    target_side_id: int,
    heal_bps: int,
) -> KernelState:
    target_side = side(state, target_side_id)
    total = 0
    for idx in MarkIdx:
        total += _unpack_mark(target_side.marks, idx)
    if total <= 0:
        return state
    actor_side = side(state, actor_side_id)
    actor = actor_side.pets[actor_slot]
    max_hp = hot.PETS[actor.pet_id][STAT_HP]
    actor = actor._replace(current_hp=min(max_hp, actor.current_hp + max_hp * heal_bps * total // BPS))
    actor_side = replace_pet(actor_side, actor_slot, actor)
    target_side = target_side._replace(marks=0)
    return replace_side(replace_side(state, actor_side_id, actor_side), target_side_id, target_side)


def _form_transform(pet: PetState, heal_full: bool) -> PetState:
    mapping = getattr(hot, "FORM_TRANSFORM_BY_PET", ())
    if pet.pet_id >= len(mapping):
        return pet
    target_id = mapping[pet.pet_id]
    if target_id <= 0 or target_id == pet.pet_id:
        return pet
    old_max = max(1, hot.PETS[pet.pet_id][STAT_HP])
    new_max = max(1, hot.PETS[target_id][STAT_HP])
    ability_id = hot.PETS[target_id][PET_ABILITY]
    ability_flags = hot.ABILITY_FLAGS[ability_id] if ability_id < len(hot.ABILITY_FLAGS) else 0
    current_hp = new_max if heal_full else max(1, min(new_max, pet.current_hp * new_max // old_max))
    transformed = pet._replace(
        pet_id=target_id,
        current_hp=current_hp,
        ability_flags=ability_flags,
        status_flags=0 if heal_full else pet.status_flags,
        status_counts=0 if heal_full else pet.status_counts,
        frostbite=0 if heal_full else pet.frostbite,
        leech_source_side=-1 if heal_full else pet.leech_source_side,
        leech_source_slot=-1 if heal_full else pet.leech_source_slot,
    )
    return transformed._replace(current_energy=energy_cap(transformed, transformed.current_energy))


def share_gains_on_side(side_state, active_slot: int, hp_gain: int, energy_gain: int, rng: int):
    """Distribute residual HP/energy gain to one non-active, non-fainted ally."""
    if hp_gain <= 0 and energy_gain <= 0:
        return side_state, rng
    count = 0
    for idx, pet in enumerate(side_state.pets):
        if idx != active_slot and not pet.fainted:
            count += 1
    if count <= 0:
        return side_state, rng
    rng = next_rng(rng)
    pick = rng % count
    chosen = -1
    seen = 0
    for idx, pet in enumerate(side_state.pets):
        if idx == active_slot or pet.fainted:
            continue
        if seen == pick:
            chosen = idx
            break
        seen += 1
    if chosen < 0:
        return side_state, rng
    pet = side_state.pets[chosen]
    if hp_gain > 0:
        pet = pet._replace(current_hp=min(hot.PETS[pet.pet_id][STAT_HP], pet.current_hp + hp_gain))
    if energy_gain > 0:
        pet = pet._replace(current_energy=energy_cap(pet, pet.current_energy + energy_gain))
    return replace_pet(side_state, chosen, pet), rng


def _add_devotion(packed: int, idx: DevotionIdx, amount: int) -> int:
    return _set_devotion(packed, idx, min(15, _unpack_devotion(packed, idx) + amount))


def _auto_switch(state: KernelState, side_id: int) -> KernelState:
    side_state = side(state, side_id)
    active = side_state.active
    for offset in range(1, len(side_state.pets) + 1):
        slot = (active + offset) % len(side_state.pets)
        if slot != active and not side_state.pets[slot].fainted:
            return switch_state(state, side_id, slot)
    return state
