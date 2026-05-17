"""Fixed battle kernel with no event bus or runtime registry."""

from __future__ import annotations

from typing import NamedTuple

from roco.config.constants import BURN_HP_CAP, ENERGY_GAIN_PER_TURN, MAX_ENERGY, MIN_DAMAGE
from roco.engine import catalog_hot as hot
from roco.engine.effect_model import EffectFlag
from roco.engine.enums import AbilityFlag, SkillCategory, StatusFlag, StatusType, WeatherType
from roco.engine.kernel_catalog import validate_catalog
from roco.engine.kernel_effects import BPS, StageCtx, TIMING_AFTER_MOVE, TIMING_CALC_DAMAGE, run_skill_timing
from roco.engine.packing import DevotionIdx, MarkIdx, _set_mark, _unpack_devotion, _unpack_mark
from roco.engine.kernel_state import (
    ACTION_MOVE,
    ACTION_SWITCH,
    NO_WINNER,
    SIDE_A,
    SIDE_B,
    WIN_A,
    WIN_B,
    WIN_DRAW,
    Choice,
    KernelState,
    PetState,
    SideState,
    has_status,
    pack_weather,
    replace_pet,
    set_status_count,
    status_stack,
    weather_turns,
    weather_type,
    with_status,
)

validate_catalog(hot)

STAT_HP = 1
STAT_ATK_PHYS = 2
STAT_ATK_MAG = 3
STAT_DEF_PHYS = 4
STAT_DEF_MAG = 5
STAT_SPEED = 6
PET_PRIMARY = 7
PET_SECONDARY = 8
SKILL_ELEMENT = 1
SKILL_CATEGORY = 2
SKILL_ENERGY = 3
SKILL_POWER = 4
SKILL_FLAGS = 5
SKILL_HIT_COUNT = 6
STAB_BPS = 15000
DAMAGE_CONST_BPS = 9000
ELEMENT_FIRE = 2
ELEMENT_WATER = 3
ELEMENT_GROUND = 5
ELEMENT_ICE = 6
ELEMENT_POISON = 9
ELEMENT_GRASS = 1
ELEMENT_MECHANICAL = 16
BURN_DAMAGE_BPS = 200
POISON_DAMAGE_BPS = 300
LEECH_DAMAGE_BPS = 800
RAIN_DAMAGE_BPS = 15000
SLOW_SPEED_REDUCE = 10
MOISTURE_COST_REDUCE = 1
MOMENTUM_COST_UP = 1
METEOR_EXTRA_DAMAGE = 30
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
    state = _end_turn(state)
    state = _check_winner(state)
    return KernelResult(state, state.winner, first_side, damage_a, damage_b)


def _start_turn(state: KernelState) -> KernelState:
    side_a = _gain_energy(state.side_a)
    side_b = _gain_energy(state.side_b)
    return state._replace(turn=state.turn + 1, side_a=side_a, side_b=side_b)


def _gain_energy(side: SideState) -> SideState:
    pets = []
    for pet in side.pets:
        if pet.fainted:
            pets.append(pet)
        else:
            pets.append(pet._replace(current_energy=min(MAX_ENERGY, pet.current_energy + ENERGY_GAIN_PER_TURN)))
    return side._replace(pets=tuple(pets))


def _order(state: KernelState, c1: Choice, c2: Choice) -> tuple[int, int]:
    pri_a = _priority(state.side_a, c1)
    pri_b = _priority(state.side_b, c2)
    if pri_a != pri_b:
        return (SIDE_A if pri_a > pri_b else SIDE_B, state.rng)
    speed_a = _marked_speed(_speed(_active_pet(state.side_a)), state.side_a.marks)
    speed_b = _marked_speed(_speed(_active_pet(state.side_b)), state.side_b.marks)
    if speed_a != speed_b:
        return (SIDE_A if speed_a > speed_b else SIDE_B, state.rng)
    rng = _next_rng(state.rng)
    return (SIDE_A if rng & 1 else SIDE_B, rng)


def _priority(side: SideState, choice: Choice) -> int:
    if choice.action_code == ACTION_SWITCH:
        return 6
    return 0


def _next_rng(value: int) -> int:
    x = value or 1
    x ^= (x << 13) & 0xFFFFFFFF
    x ^= (x >> 17) & 0xFFFFFFFF
    x ^= (x << 5) & 0xFFFFFFFF
    return x & 0xFFFFFFFF


def _execute(
    state: KernelState,
    actor_side_id: int,
    choice: Choice,
    target_side_id: int,
    ctx: StageCtx,
    first_strike: bool,
) -> tuple[KernelState, int]:
    actor_side = _side(state, actor_side_id)
    target_side = _side(state, target_side_id)
    actor_slot = actor_side.active
    target_slot = target_side.active
    actor = actor_side.pets[actor_slot]
    target = target_side.pets[target_slot]
    if actor.fainted:
        return state, 0
    if choice.action_code == ACTION_SWITCH:
        return _switch(state, actor_side_id, choice.data), 0
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
    cost = _marked_skill_cost(cost, actor_side.marks, is_attack)
    devotion_active = bool(skill[SKILL_FLAGS] & int(EffectFlag.DEVOTION))
    if devotion_active:
        cost = max(0, cost - _unpack_devotion(actor_side.devotion, DevotionIdx.JIAMEI))
    if weather_type(state.weather) == WeatherType.SANDSTORM.value and skill[SKILL_ELEMENT] == ELEMENT_GROUND:
        cost //= 2
    if actor.current_energy < cost:
        return state, 0
    actor = actor._replace(current_energy=max(0, actor.current_energy - cost))
    actor_side = replace_pet(actor_side, actor_slot, actor)
    state = _replace_side(state, actor_side_id, actor_side)
    damage = 0
    ctx.reset(actor_side_id, actor_slot, target_side_id, target_slot, skill_id)
    ctx.power = skill[SKILL_POWER]
    ctx.hit_count = skill[SKILL_HIT_COUNT]
    if devotion_active:
        ctx.power_bps += _unpack_devotion(actor_side.devotion, DevotionIdx.FEIDUAN) * 1000
        ctx.hit_count += _unpack_devotion(actor_side.devotion, DevotionIdx.CHONGQUN)
    if is_attack:
        run_skill_timing(hot.SKILL_EFFECT_ROWS, hot.SKILL_EFFECT_RANGES[skill_id], TIMING_CALC_DAMAGE, ctx)
        damage = _damage(actor, target, skill, ctx, state.weather, actor_side.marks, target_side.marks, first_strike)
        next_hp = target.current_hp - damage
        if next_hp <= 0 and target.cute >= 5:
            target = target._replace(current_hp=1, cute=target.cute - 5)
        else:
            target = target._replace(current_hp=max(0, next_hp))
        target_side = replace_pet(target_side, target_slot, target)
        state = _replace_side(state, target_side_id, target_side)
        if target.current_hp <= 0:
            state = _faint_pet(state, target_side_id, target_slot, actor_side_id, actor_slot)
    run_skill_timing(hot.SKILL_EFFECT_ROWS, hot.SKILL_EFFECT_RANGES[skill_id], TIMING_AFTER_MOVE, ctx)
    state = _apply_after_move(state, actor_side_id, actor_slot, target_side_id, target_slot, ctx)
    state = _clear_barrel_after_action(state, actor_side_id, actor_slot)
    return state, damage


def _switch(state: KernelState, side_id: int, slot: int) -> KernelState:
    side = _side(state, side_id)
    if slot < 0 or slot >= len(side.pets):
        return state
    if side.pets[slot].fainted:
        return state
    outgoing = side.pets[side.active]
    if outgoing.ability_flags & int(AbilityFlag.BARREL_ACTIVE):
        side = side._replace(barrel_pending=1)
    side = side._replace(active=slot)
    if side.barrel_pending:
        incoming = side.pets[slot]._replace(ability_flags=side.pets[slot].ability_flags | int(AbilityFlag.BARREL_ACTIVE))
        side = replace_pet(side, slot, incoming)._replace(barrel_pending=0)
    side = _apply_switch_in_marks(side, slot)
    return _replace_side(state, side_id, side)


def _damage(
    actor: PetState,
    target: PetState,
    skill: tuple[int, ...],
    ctx: StageCtx,
    weather: int = 0,
    actor_marks: int = 0,
    target_marks: int = 0,
    first_strike: bool = True,
) -> int:
    actor_row = hot.PETS[actor.pet_id]
    target_row = hot.PETS[target.pet_id]
    physical = skill[SKILL_CATEGORY] == SkillCategory.PHYSICAL.value
    atk = actor_row[STAT_ATK_PHYS] if physical else actor_row[STAT_ATK_MAG]
    defense = target_row[STAT_DEF_PHYS] if physical else target_row[STAT_DEF_MAG]
    if ctx.power <= 0 or atk <= 0 or defense <= 1:
        return 0
    power = max(0, (ctx.power * ctx.power_bps) // BPS)
    type_bps = BPS if actor.ability_flags & int(AbilityFlag.BARREL_ACTIVE) else _type_bps(skill[SKILL_ELEMENT], target_row[PET_PRIMARY], target_row[PET_SECONDARY])
    stab_bps = STAB_BPS if skill[SKILL_ELEMENT] == actor_row[PET_PRIMARY] else BPS
    weather_bps = _weather_damage_bps(skill[SKILL_ELEMENT], weather)
    mark_bps = _mark_attack_bps(actor_marks, first_strike, skill[SKILL_ENERGY])
    cute_bps = BPS + actor.cute * 500
    per_hit = (
        atk
        * power
        * DAMAGE_CONST_BPS
        * type_bps
        * stab_bps
        * weather_bps
        * mark_bps
        * cute_bps
    ) // (defense * BPS * BPS * BPS * BPS * BPS * BPS)
    per_hit = max(MIN_DAMAGE, per_hit)
    total = per_hit * max(1, ctx.hit_count)
    if skill[SKILL_ELEMENT] != 17:
        total += _unpack_mark(target_marks, MarkIdx.METEOR) * METEOR_EXTRA_DAMAGE
    total += ctx.flat_damage
    return max(0, (total * ctx.damage_bps) // BPS)


def _weather_damage_bps(skill_element: int, weather: int) -> int:
    if weather_type(weather) == WeatherType.RAIN.value and skill_element == ELEMENT_WATER:
        return RAIN_DAMAGE_BPS
    return BPS


def _marked_speed(speed: int, marks: int) -> int:
    return max(1, speed - _unpack_mark(marks, MarkIdx.SLOW) * SLOW_SPEED_REDUCE)


def _marked_skill_cost(cost: int, marks: int, is_attack: bool) -> int:
    cost -= _unpack_mark(marks, MarkIdx.MOISTURE) * MOISTURE_COST_REDUCE
    if is_attack:
        cost += _unpack_mark(marks, MarkIdx.MOMENTUM) * MOMENTUM_COST_UP
    return max(0, cost)


def _mark_attack_bps(marks: int, first_strike: bool, base_energy: int) -> int:
    bonus = 0
    bonus += _unpack_mark(marks, MarkIdx.ATTACK) * 1000
    bonus += _unpack_mark(marks, MarkIdx.MOMENTUM) * 3000
    if first_strike:
        bonus += _unpack_mark(marks, MarkIdx.WIND) * 2000
    else:
        bonus += _unpack_mark(marks, MarkIdx.SLUGGISH) * 3000
    if base_energy == 5:
        bonus += _unpack_mark(marks, MarkIdx.DRAGON) * 4000
    return BPS + bonus


def _same_polarity_mask(idx: MarkIdx) -> int:
    return POSITIVE_MARK_MASK if POSITIVE_MARK_MASK & (0xF << (idx.value * 4)) else NEGATIVE_MARK_MASK


def _apply_mark_delta(current: int, delta: int) -> int:
    marks = current
    for idx in MarkIdx:
        stacks = _unpack_mark(delta, idx)
        if stacks <= 0:
            continue
        keep = 0xF << (idx.value * 4)
        marks &= ~(_same_polarity_mask(idx) & ~keep)
        marks = _set_mark(marks, idx, min(15, _unpack_mark(marks, idx) + stacks))
    return marks


def _apply_switch_in_marks(side: SideState, slot: int) -> SideState:
    pet = side.pets[slot]
    thorn = _unpack_mark(side.marks, MarkIdx.THORN)
    spirit = _unpack_mark(side.marks, MarkIdx.SPIRIT)
    if thorn > 0:
        pet = pet._replace(current_hp=max(0, pet.current_hp - hot.PETS[pet.pet_id][STAT_HP] * thorn * 600 // BPS))
    if spirit > 0:
        pet = pet._replace(current_energy=max(0, pet.current_energy - spirit))
    return replace_pet(side, slot, pet)


def _clear_barrel_after_action(state: KernelState, side_id: int, slot: int) -> KernelState:
    side = _side(state, side_id)
    pet = side.pets[slot]
    if pet.ability_flags & int(AbilityFlag.BARREL_ACTIVE):
        pet = pet._replace(ability_flags=pet.ability_flags & ~int(AbilityFlag.BARREL_ACTIVE))
        side = replace_pet(side, slot, pet)
        state = _replace_side(state, side_id, side)
    return state


def _apply_after_move(
    state: KernelState,
    actor_side_id: int,
    actor_slot: int,
    target_side_id: int,
    target_slot: int,
    ctx: StageCtx,
) -> KernelState:
    if ctx.weather:
        state = state._replace(weather=pack_weather(ctx.weather, ctx.weather_turns))
    actor_side = _side(state, actor_side_id)
    target_side = _side(state, target_side_id)
    if ctx.clear_self_marks:
        actor_side = actor_side._replace(marks=0)
    if ctx.clear_enemy_marks:
        target_side = target_side._replace(marks=0)
    if ctx.mark_self:
        actor_side = actor_side._replace(marks=_apply_mark_delta(actor_side.marks, ctx.mark_self))
    if ctx.mark_enemy:
        target_side = target_side._replace(marks=_apply_mark_delta(target_side.marks, ctx.mark_enemy))
    state = _replace_side(state, actor_side_id, actor_side)
    state = _replace_side(state, target_side_id, target_side)
    target_side = _side(state, target_side_id)
    target = target_side.pets[target_slot]
    target = _apply_status_effect(target, StatusType.BURN, StatusFlag.BURN, ctx.burn_stacks, actor_side_id, actor_slot)
    target = _apply_status_effect(target, StatusType.POISON, StatusFlag.POISON, ctx.poison_stacks, actor_side_id, actor_slot)
    target = _apply_status_effect(target, StatusType.FREEZE, StatusFlag.FREEZE, ctx.freeze_stacks, actor_side_id, actor_slot)
    target = _apply_status_effect(target, StatusType.LEECH, StatusFlag.LEECH, ctx.leech_stacks, actor_side_id, actor_slot)
    target_side = replace_pet(target_side, target_slot, target)
    return _replace_side(state, target_side_id, target_side)


def _apply_status_effect(
    pet: PetState,
    status: StatusType,
    flag: StatusFlag,
    stacks: int,
    source_side: int,
    source_slot: int,
) -> PetState:
    if stacks <= 0:
        return pet
    if status != StatusType.LEECH and _status_immune(pet, flag):
        return pet
    pet = with_status(pet, status, stacks)
    if status == StatusType.LEECH:
        pet = pet._replace(leech_source_side=source_side, leech_source_slot=source_slot)
    return pet


def _status_immune(pet: PetState, flag: StatusFlag) -> bool:
    row = hot.PETS[pet.pet_id]
    primary = row[PET_PRIMARY]
    secondary = row[PET_SECONDARY]
    if flag == StatusFlag.BURN:
        return primary == ELEMENT_FIRE or secondary == ELEMENT_FIRE
    if flag == StatusFlag.POISON:
        return primary == ELEMENT_POISON or secondary == ELEMENT_POISON
    if flag == StatusFlag.FREEZE:
        return primary == ELEMENT_ICE or secondary == ELEMENT_ICE
    return False


def _end_turn(state: KernelState) -> KernelState:
    state = _tick_leech(state)
    state = _tick_marks(state)
    state = _tick_weather(state)
    state = _tick_status(state)
    return _mark_zero_hp_fainted(state)


def _tick_leech(state: KernelState) -> KernelState:
    for side_id in (SIDE_A, SIDE_B):
        side = _side(state, side_id)
        slot = side.active
        pet = side.pets[slot]
        stacks = status_stack(pet, StatusType.LEECH)
        if pet.fainted or stacks <= 0 or pet.leech_source_side < 0:
            continue
        damage = hot.PETS[pet.pet_id][STAT_HP] * stacks * LEECH_DAMAGE_BPS // BPS
        pet = pet._replace(current_hp=max(0, pet.current_hp - damage))
        side = replace_pet(side, slot, pet)
        state = _replace_side(state, side_id, side)
        source_side = _side(state, pet.leech_source_side)
        source_slot = pet.leech_source_slot
        if 0 <= source_slot < len(source_side.pets):
            source = source_side.pets[source_slot]
            if not source.fainted:
                max_hp = hot.PETS[source.pet_id][STAT_HP]
                source = source._replace(current_hp=min(max_hp, source.current_hp + damage))
                source_side = replace_pet(source_side, source_slot, source)
                state = _replace_side(state, pet.leech_source_side, source_side)
    return state


def _tick_marks(state: KernelState) -> KernelState:
    for side_id in (SIDE_A, SIDE_B):
        side = _side(state, side_id)
        pet = side.pets[side.active]
        if pet.fainted:
            continue
        poison = _unpack_mark(side.marks, MarkIdx.POISON)
        solar = _unpack_mark(side.marks, MarkIdx.SOLAR)
        if poison > 0:
            damage = hot.PETS[pet.pet_id][STAT_HP] * poison * POISON_DAMAGE_BPS // BPS
            pet = pet._replace(current_hp=max(0, pet.current_hp - damage))
        if solar > 0:
            pet = pet._replace(current_energy=min(MAX_ENERGY, pet.current_energy + solar))
        side = replace_pet(side, side.active, pet)
        state = _replace_side(state, side_id, side)
    return state


def _tick_weather(state: KernelState) -> KernelState:
    current = weather_type(state.weather)
    turns = weather_turns(state.weather)
    if current == WeatherType.NONE.value:
        return state
    for side_id in (SIDE_A, SIDE_B):
        side = _side(state, side_id)
        slot = side.active
        pet = side.pets[slot]
        if pet.fainted:
            continue
        if current == WeatherType.SANDSTORM.value and not _sandstorm_immune(pet):
            damage = hot.PETS[pet.pet_id][STAT_HP] // 16
            pet = pet._replace(current_hp=max(0, pet.current_hp - damage))
        elif current == WeatherType.SNOW.value:
            max_hp = hot.PETS[pet.pet_id][STAT_HP]
            pet = pet._replace(frostbite=pet.frostbite + max_hp // 12)
            pet = with_status(pet, StatusType.FREEZE, 2)
        side = replace_pet(side, slot, pet)
        state = _replace_side(state, side_id, side)
    if turns > 0:
        turns -= 1
        state = state._replace(weather=pack_weather(current, turns) if turns > 0 else 0)
    return state


def _sandstorm_immune(pet: PetState) -> bool:
    row = hot.PETS[pet.pet_id]
    return row[PET_PRIMARY] in (ELEMENT_GROUND, ELEMENT_MECHANICAL) or row[PET_SECONDARY] in (ELEMENT_GROUND, ELEMENT_MECHANICAL)


def _tick_status(state: KernelState) -> KernelState:
    for side_id, enemy_side_id in ((SIDE_A, SIDE_B), (SIDE_B, SIDE_A)):
        side = _side(state, side_id)
        enemy = _active_pet(_side(state, enemy_side_id))
        slot = side.active
        pet = side.pets[slot]
        if pet.fainted:
            continue
        if has_status(pet, StatusFlag.BURN):
            stacks = status_stack(pet, StatusType.BURN)
            damage = _burn_damage(pet, stacks)
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
        side = replace_pet(side, slot, pet)
        state = _replace_side(state, side_id, side)
    return state


def _burn_damage(pet: PetState, stacks: int) -> int:
    if stacks <= 0:
        return 0
    row = hot.PETS[pet.pet_id]
    hp = min(row[STAT_HP], BURN_HP_CAP)
    type_bps = _type_bps(ELEMENT_FIRE, row[PET_PRIMARY], row[PET_SECONDARY])
    return hp * stacks * BURN_DAMAGE_BPS * type_bps // (BPS * BPS)


def _mark_zero_hp_fainted(state: KernelState) -> KernelState:
    for side_id in (SIDE_A, SIDE_B):
        side = _side(state, side_id)
        for slot, pet in enumerate(side.pets):
            if pet.current_hp <= 0 and not pet.fainted:
                state = _faint_pet(state, side_id, slot)
                side = _side(state, side_id)
    return state


def _faint_pet(
    state: KernelState,
    side_id: int,
    slot: int,
    killer_side_id: int = -1,
    killer_slot: int = -1,
) -> KernelState:
    side = _side(state, side_id)
    pet = side.pets[slot]
    if pet.fainted:
        return state
    magic_cost = 0 if pet.ability_flags & int(AbilityFlag.FAKE_DEATH) else 1
    pet = pet._replace(current_hp=0, fainted=1)
    if pet.cute > 0 and killer_side_id >= 0:
        killer_side = _side(state, killer_side_id)
        if 0 <= killer_slot < len(killer_side.pets):
            killer = killer_side.pets[killer_slot]
            if not killer.fainted:
                killer = killer._replace(cute=killer.cute + pet.cute)
                killer_side = replace_pet(killer_side, killer_slot, killer)
                state = _replace_side(state, killer_side_id, killer_side)
                pet = pet._replace(cute=0)
                side = _side(state, side_id)
    side = replace_pet(side, slot, pet)._replace(magic=max(0, side.magic - magic_cost))
    if slot == side.active:
        for idx, candidate in enumerate(side.pets):
            if idx != slot and not candidate.fainted:
                side = side._replace(active=idx)
                side = _apply_switch_in_marks(side, idx)
                break
    return _replace_side(state, side_id, side)


def _type_bps(move_element: int, primary: int, secondary: int) -> int:
    first = hot.TYPE_CHART_BPS[move_element][primary]
    if secondary < 0:
        return first
    second = hot.TYPE_CHART_BPS[move_element][secondary]
    if first > BPS and second > BPS:
        return 30000
    if first < BPS and second < BPS:
        return 2500
    if (first > BPS and second < BPS) or (first < BPS and second > BPS):
        return BPS
    return first if first != BPS else second


def _check_winner(state: KernelState) -> KernelState:
    alive_a = _has_alive(state.side_a)
    alive_b = _has_alive(state.side_b)
    winner = NO_WINNER
    if not alive_a and not alive_b:
        winner = WIN_DRAW
    elif not alive_a:
        winner = WIN_B
    elif not alive_b:
        winner = WIN_A
    return state._replace(winner=winner)


def _has_alive(side: SideState) -> bool:
    for pet in side.pets:
        if not pet.fainted:
            return True
    return False


def _active_pet(side: SideState) -> PetState:
    return side.pets[side.active]


def _speed(pet: PetState) -> int:
    return hot.PETS[pet.pet_id][STAT_SPEED]


def _side(state: KernelState, side_id: int) -> SideState:
    return state.side_a if side_id == SIDE_A else state.side_b


def _replace_side(state: KernelState, side_id: int, side: SideState) -> KernelState:
    if side_id == SIDE_A:
        return state._replace(side_a=side)
    return state._replace(side_b=side)
