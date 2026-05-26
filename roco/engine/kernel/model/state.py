"""Fixed-kernel battle state made of integer ids and packed fields."""

from __future__ import annotations

from typing import NamedTuple

from roco.common.constants import LEADER_USES, MAGIC_WILLPOWER, SIDE_LIVES, STARTING_ENERGY, WILLPOWER_USES
from roco.generated.catalog import hot
from roco.generated.pak.bloodline_magic import PAK_ELEMENT_TO_BLOODLINE
from roco.common.enums import AbilityFlag, StatusFlag, StatusType, WeatherType
from roco.engine.common.choices import NO_WINNER, SIDE_A
from roco.common.packing import _pack_buff, _set_status, _unpack_status

COST_SCOPE_NONE = 0
COST_SCOPE_ALL = 1
COST_SCOPE_CURRENT_SLOT = 2
COST_SCOPE_OTHER_SLOTS = 3
COST_SCOPE_ATTACK = 4


class PetState(NamedTuple):
    pet_id: int
    current_hp: int
    current_energy: int
    buff_stages: int
    status_flags: int
    status_counts: int
    cooldowns: int
    ability_flags: int
    priority_boost: int
    lifedrain_bps: int
    hit_delta: int
    global_cost_delta: int
    attack_cost_delta: int
    global_power_bonus: int
    anti_heal_multiplier: int
    first_action_done: int
    counter_success_count: int
    frostbite: int
    cute: int
    leech_source_side: int
    leech_source_slot: int
    fainted: int
    # Packed active-buff ledger: 8 lanes × 64 bits per
    # ``roco.engine.kernel.model.active_buffs`` schema.  Default 0 = all lanes
    # empty, so existing code paths that never touch the ledger are
    # behaviour-neutral.
    active_buffs: int = 0
    element_power_flat: int = 0
    element_power_bps: int = 0
    element_cost_reduce: int = 0
    element_poison_stacks: int = 0
    element_damage_reduce: int = 0
    element_damage_resist: int = 0
    switch_lock_turns: int = 0


class SideState(NamedTuple):
    active: int
    side_lives: int
    willpower_uses: int
    leader_uses: int
    bloodline_magic_id: int
    marks: int
    devotion: int
    burst_entries: int
    barrel_pending: int
    skill_counts: int
    status_skill_count: int
    defense_skill_count: int
    skill_dam_type_counts: int
    switch_count: int
    counter_count: int
    cost_mods: int
    pets: tuple[PetState, ...]
    moves: tuple[tuple[int, int, int, int], ...]
    bloodlines: tuple[int, ...]
    # 70xxxxx "应对！X" counter response skill installed on the active
    # pet by the pak 1031xxx counter-trigger family.  Consumed (and
    # cleared) by ``mechanics`` on the next incoming hit.  Zero means
    # no counter is armed.
    counter_skill_id: int = 0


class KernelState(NamedTuple):
    turn: int
    weather: int
    rng: int
    winner: int
    side_a: SideState
    side_b: SideState
    # Per-actor mark-dispel tallies for the current turn.  Indexed by the
    # *actor* side id (the side whose move did the dispel), not the side
    # whose marks got cleared — so a self-clear by A and an enemy-clear
    # by A both credit ``marks_dispelled_a``, regardless of which side
    # owned the marks.  Consumed by ``op_dispel_marks_to_burn`` at
    # TURN_END so each actor's mark→burn payload only sees the marks its
    # *own* dispel rows removed (e.g. 焚烧烙印's 1042014 does not pick up
    # an opposing skill's incidental clear).  Both reset in
    # ``mechanics._start_turn``.
    marks_dispelled_a: int = 0
    marks_dispelled_b: int = 0


def pack_weather(weather: int, turns: int) -> int:
    return (weather & 0xF) | ((turns & 0xF) << 4)


def weather_type(weather: int) -> int:
    return weather & 0xF


def weather_turns(weather: int) -> int:
    return (weather >> 4) & 0xF


def pack_cost_mod(amount: int, turns: int, scope: int, slot: int) -> int:
    return (max(0, min(15, amount)) | (max(0, min(15, turns)) << 4) | ((scope & 0xF) << 8) | ((slot & 0xF) << 12))


def cost_mod_amount(packed: int, slot: int, category: int) -> int:
    turns = (packed >> 4) & 0xF
    if turns <= 0:
        return 0
    amount = packed & 0xF
    scope = (packed >> 8) & 0xF
    stored_slot = (packed >> 12) & 0xF
    if scope == COST_SCOPE_ALL:
        return amount
    if scope == COST_SCOPE_CURRENT_SLOT and slot == stored_slot:
        return amount
    if scope == COST_SCOPE_OTHER_SLOTS and 0 <= slot != stored_slot:
        return amount
    if scope == COST_SCOPE_ATTACK and category in (1, 2):
        return amount
    return 0


def tick_cost_mod(packed: int) -> int:
    turns = (packed >> 4) & 0xF
    if turns <= 1:
        return 0
    return pack_cost_mod(packed & 0xF, turns - 1, (packed >> 8) & 0xF, (packed >> 12) & 0xF)


def status_stack(pet: PetState, status: StatusType) -> int:
    return _unpack_status(pet.status_counts, status)


def with_status(pet: PetState, status: StatusType, stacks: int) -> PetState:
    if stacks <= 0:
        return pet
    return pet._replace(
        status_flags=pet.status_flags | int(status.flag),
        status_counts=_set_status(pet.status_counts, status, status_stack(pet, status) + stacks),
    )


def without_status(pet: PetState, status: StatusType) -> PetState:
    return pet._replace(
        status_flags=pet.status_flags & ~int(status.flag),
        status_counts=_set_status(pet.status_counts, status, 0),
    )


def set_status_count(pet: PetState, status: StatusType, stacks: int) -> PetState:
    flags = pet.status_flags | int(status.flag) if stacks > 0 else pet.status_flags & ~int(status.flag)
    return pet._replace(status_flags=flags, status_counts=_set_status(pet.status_counts, status, stacks))


def has_status(pet: PetState, flag: StatusFlag) -> bool:
    return bool(pet.status_flags & int(flag))


def _pet_state(pet_id: int) -> PetState:
    row = hot.PETS[pet_id]
    ability_id = row[9]
    ability_flags = hot.ABILITY_FLAGS[ability_id] if ability_id < len(hot.ABILITY_FLAGS) else 0
    energy = 0 if ability_flags & int(AbilityFlag.START_ZERO_ENERGY) else STARTING_ENERGY
    return PetState(
        pet_id=pet_id,
        current_hp=row[1],
        current_energy=energy,
        buff_stages=_pack_buff(),
        status_flags=0,
        status_counts=0,
        cooldowns=0,
        ability_flags=ability_flags,
        priority_boost=0,
        lifedrain_bps=0,
        hit_delta=0,
        global_cost_delta=0,
        attack_cost_delta=0,
        global_power_bonus=0,
        anti_heal_multiplier=0,
        first_action_done=0,
        counter_success_count=0,
        frostbite=0,
        cute=0,
        leech_source_side=-1,
        leech_source_slot=-1,
        fainted=0,
        active_buffs=0,
        element_power_flat=0,
        element_power_bps=0,
        element_cost_reduce=0,
        element_poison_stacks=0,
        element_damage_reduce=0,
        element_damage_resist=0,
        switch_lock_turns=0,
    )


def _move_row(pet_id: int, override: tuple[int, ...] | None) -> tuple[int, int, int, int]:
    ids = override if override is not None else hot.PET_SKILLS[pet_id]
    return tuple((tuple(ids) + (0, 0, 0, 0))[:4])  # type: ignore[return-value]


def _bloodline_row(pet_id: int, override: int | None) -> int:
    if override is not None and override >= 0:
        return override
    primary = hot.PETS[pet_id][7]
    return PAK_ELEMENT_TO_BLOODLINE[primary]


def make_side(
    pet_ids: tuple[int, ...],
    move_rows: tuple[tuple[int, ...], ...] | None = None,
    bloodlines: tuple[int, ...] | None = None,
    bloodline_magic_id: int = MAGIC_WILLPOWER,
) -> SideState:
    pets = tuple(_pet_state(pet_id) for pet_id in pet_ids)
    moves = tuple(_move_row(pet_id, move_rows[idx] if move_rows and idx < len(move_rows) else None)
                  for idx, pet_id in enumerate(pet_ids))
    bloodline_rows = tuple(
        _bloodline_row(pet_id, bloodlines[idx] if bloodlines and idx < len(bloodlines) else None)
        for idx, pet_id in enumerate(pet_ids)
    )
    return SideState(
        0,
        SIDE_LIVES,
        WILLPOWER_USES,
        LEADER_USES,
        bloodline_magic_id,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        pets,
        moves,
        bloodline_rows,
        0,
    )


def make_state(
    team_a: tuple[int, ...],
    team_b: tuple[int, ...],
    *,
    team_a_moves: tuple[tuple[int, ...], ...] | None = None,
    team_b_moves: tuple[tuple[int, ...], ...] | None = None,
    team_a_bloodlines: tuple[int, ...] | None = None,
    team_b_bloodlines: tuple[int, ...] | None = None,
    team_a_bloodline_magic_id: int = MAGIC_WILLPOWER,
    team_b_bloodline_magic_id: int = MAGIC_WILLPOWER,
    weather: int = WeatherType.NONE.value,
    weather_duration: int = 0,
    rng_seed: int = 1,
) -> KernelState:
    return KernelState(
        turn=0,
        weather=pack_weather(weather, weather_duration),
        rng=rng_seed & 0xFFFFFFFF,
        winner=NO_WINNER,
        side_a=make_side(team_a, team_a_moves, team_a_bloodlines, team_a_bloodline_magic_id),
        side_b=make_side(team_b, team_b_moves, team_b_bloodlines, team_b_bloodline_magic_id),
    )


def copy_state(state: KernelState) -> KernelState:
    side_a = SideState(
        state.side_a.active,
        state.side_a.side_lives,
        state.side_a.willpower_uses,
        state.side_a.leader_uses,
        state.side_a.bloodline_magic_id,
        state.side_a.marks,
        state.side_a.devotion,
        state.side_a.burst_entries,
        state.side_a.barrel_pending,
        state.side_a.skill_counts,
        state.side_a.status_skill_count,
        state.side_a.defense_skill_count,
        state.side_a.skill_dam_type_counts,
        state.side_a.switch_count,
        state.side_a.counter_count,
        state.side_a.cost_mods,
        tuple(PetState(*pet) for pet in state.side_a.pets),
        tuple(tuple(row) for row in state.side_a.moves),
        tuple(state.side_a.bloodlines),
        state.side_a.counter_skill_id,
    )
    side_b = SideState(
        state.side_b.active,
        state.side_b.side_lives,
        state.side_b.willpower_uses,
        state.side_b.leader_uses,
        state.side_b.bloodline_magic_id,
        state.side_b.marks,
        state.side_b.devotion,
        state.side_b.burst_entries,
        state.side_b.barrel_pending,
        state.side_b.skill_counts,
        state.side_b.status_skill_count,
        state.side_b.defense_skill_count,
        state.side_b.skill_dam_type_counts,
        state.side_b.switch_count,
        state.side_b.counter_count,
        state.side_b.cost_mods,
        tuple(PetState(*pet) for pet in state.side_b.pets),
        tuple(tuple(row) for row in state.side_b.moves),
        tuple(state.side_b.bloodlines),
        state.side_b.counter_skill_id,
    )
    return KernelState(
        state.turn,
        state.weather,
        state.rng,
        state.winner,
        side_a,
        side_b,
        state.marks_dispelled_a,
        state.marks_dispelled_b,
    )


def replace_pet(side: SideState, slot: int, pet: PetState) -> SideState:
    pets = side.pets[:slot] + (pet,) + side.pets[slot + 1:]
    return side._replace(pets=pets)


def side(state: KernelState, side_id: int) -> SideState:
    return state.side_a if side_id == SIDE_A else state.side_b


def replace_side(state: KernelState, side_id: int, value: SideState) -> KernelState:
    if side_id == SIDE_A:
        return state._replace(side_a=value)
    return state._replace(side_b=value)


def active_pet(side_state: SideState) -> PetState:
    return side_state.pets[side_state.active]
