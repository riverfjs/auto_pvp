"""Turn ordering and move-choice helpers for the battle kernel."""

from __future__ import annotations

from roco.common.constants import MAGIC_LEADER_TRANSFORM, MAGIC_WILLPOWER
from roco.common.enums import AbilityFlag, SkillCategory
from roco.engine.common.choices import ACTION_MAGIC, ACTION_MOVE, ACTION_SWITCH, SIDE_A, SIDE_B, Choice
from roco.engine.common.rng import next_rng
from roco.engine.kernel.catalog import (
    PET_ABILITY,
    SKILL_CATEGORY,
    SKILL_ENERGY,
    SKILL_FLAG_AGILITY,
    SKILL_FLAGS,
    STAT_SPEED,
)
from roco.engine.kernel.damage import marked_speed
from roco.engine.kernel.state import (
    COST_SCOPE_CURRENT_SLOT,
    KernelState,
    PetState,
    active_pet,
    pack_cost_mod,
    replace_pet,
    replace_side,
    side,
)
from roco.generated import catalog_hot as hot
from roco.generated.handler_order import op_index

OP_BORROW_TEAM_SKILL = op_index("op_borrow_team_skill")
OP_SKILL_MOD = op_index("op_skill_mod")


def choice_to_skill_id(state: KernelState, side_id: int, choice: Choice) -> int:
    if choice.action_code != ACTION_MOVE or not (0 <= choice.data < 4):
        return 0
    side_state = side(state, side_id)
    return side_state.moves[side_state.active][choice.data]


def start_turn(state: KernelState) -> KernelState:
    state = state._replace(
        turn=state.turn + 1,
        marks_dispelled_a=0,
        marks_dispelled_b=0,
    )
    state, rng = _start_turn_side(state, SIDE_A, state.rng)
    state, rng = _start_turn_side(state._replace(rng=rng), SIDE_B, rng)
    return state._replace(rng=rng)


def order(state: KernelState, c1: Choice, c2: Choice) -> tuple[int, int]:
    pri_a = _priority(state, SIDE_A, c1)
    pri_b = _priority(state, SIDE_B, c2)
    if pri_a != pri_b:
        return (SIDE_A if pri_a > pri_b else SIDE_B, state.rng)
    speed_a = marked_speed(_speed(active_pet(state.side_a)), state.side_a.marks)
    speed_b = marked_speed(_speed(active_pet(state.side_b)), state.side_b.marks)
    if speed_a != speed_b:
        return (SIDE_A if speed_a > speed_b else SIDE_B, state.rng)
    rng = next_rng(state.rng)
    return (SIDE_A if rng & 1 else SIDE_B, rng)


def choice_category(state: KernelState, side_id: int, choice: Choice) -> int:
    if choice.action_code == ACTION_MAGIC:
        magic_id = side(state, side_id).bloodline_magic_id
        if magic_id == MAGIC_LEADER_TRANSFORM:
            return 0
        if magic_id == MAGIC_WILLPOWER:
            return SkillCategory.MAGICAL.value
        return 0
    if choice.action_code != ACTION_MOVE:
        return 0
    side_state = side(state, side_id)
    if choice.data < 0 or choice.data >= 4:
        return 0
    skill_id = side_state.moves[side_state.active][choice.data]
    if skill_id <= 0:
        return 0
    return hot.SKILLS[skill_id][SKILL_CATEGORY]


def target_skill_energy(target_side, target_slot: int, target_skill_slot: int) -> int:
    if target_skill_slot < 0 or target_skill_slot >= 4:
        return 0
    skill_id = target_side.moves[target_slot][target_skill_slot]
    if skill_id <= 0:
        return 0
    return hot.SKILLS[skill_id][SKILL_ENERGY]


def borrowed_skill_id(side_state, actor_slot: int, skill_id: int, rng: int) -> int:
    start, end = hot.SKILL_EFFECT_RANGES[skill_id]
    has_borrow = 0
    for idx in range(start, end):
        if hot.SKILL_EFFECT_ROWS[idx][0] == OP_BORROW_TEAM_SKILL:
            has_borrow = 1
    if not has_borrow:
        return 0
    count = 0
    fallback = 0
    target_index = rng & 0xF
    for slot, moves in enumerate(side_state.moves):
        if slot == actor_slot:
            continue
        for candidate in moves:
            if candidate <= 0:
                continue
            if count == target_index:
                return candidate
            fallback = candidate
            count += 1
    return fallback


def _start_turn_side(state: KernelState, side_id: int, rng: int) -> tuple[KernelState, int]:
    side_state = side(state, side_id)
    slot = side_state.active
    pet = side_state.pets[slot]
    if pet.fainted or not (pet.ability_flags & int(AbilityFlag.SHUFFLE_SKILLS_REDUCE_LAST)):
        return state, rng
    moves, rng = _shuffle_four(side_state.moves[slot], rng)
    side_state = side_state._replace(
        moves=side_state.moves[:slot] + (moves,) + side_state.moves[slot + 1:],
        cost_mods=pack_cost_mod(4, 1, COST_SCOPE_CURRENT_SLOT, 3),
    )
    return replace_side(state, side_id, side_state), rng


def _shuffle_four(values: tuple[int, int, int, int], rng: int) -> tuple[tuple[int, int, int, int], int]:
    data = [values[0], values[1], values[2], values[3]]
    for idx in (3, 2, 1):
        rng = next_rng(rng)
        swap = rng % (idx + 1)
        data[idx], data[swap] = data[swap], data[idx]
    return (data[0], data[1], data[2], data[3]), rng


def _priority(state: KernelState, side_id: int, choice: Choice) -> int:
    if choice.action_code == ACTION_SWITCH:
        return 6
    side_state = side(state, side_id)
    pet = side_state.pets[side_state.active]
    priority = pet.priority_boost
    if choice.action_code == ACTION_MOVE and 0 <= choice.data < 4:
        skill_id = side_state.moves[side_state.active][choice.data]
        if skill_id > 0 and hot.SKILLS[skill_id][SKILL_FLAGS] & SKILL_FLAG_AGILITY:
            priority += 1
        priority += _ability_slot_priority(pet, choice.data)
    return priority


def _ability_slot_priority(actor: PetState, slot_idx: int) -> int:
    ability_id = hot.PETS[actor.pet_id][PET_ABILITY]
    if ability_id <= 0 or ability_id >= len(hot.ABILITY_EFFECT_RANGES):
        return 0
    start, end = hot.ABILITY_EFFECT_RANGES[ability_id]
    priority = 0
    for idx in range(start, end):
        row = hot.ABILITY_EFFECT_ROWS[idx]
        if row[0] == OP_SKILL_MOD and row[1] == 0 and row[5] & (1 << slot_idx):
            priority += row[6]
    return priority


def _speed(pet: PetState) -> int:
    return hot.PETS[pet.pet_id][STAT_SPEED]
