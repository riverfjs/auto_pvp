"""Fixed-kernel battle state made of integer ids and packed fields."""

from __future__ import annotations

from typing import NamedTuple

from roco.config.constants import STARTING_ENERGY
from roco.engine import catalog_hot as hot
from roco.engine.enums import StatusFlag, StatusType, WeatherType
from roco.engine.packing import _pack_buff, _set_status, _unpack_status

ACTION_MOVE = 1
ACTION_SWITCH = 2
SIDE_A = 0
SIDE_B = 1
NO_WINNER = 0
WIN_A = 1
WIN_B = 2
WIN_DRAW = 3


class Choice(NamedTuple):
    action_code: int
    data: int


class PetState(NamedTuple):
    pet_id: int
    current_hp: int
    current_energy: int
    buff_stages: int
    status_flags: int
    status_counts: int
    cooldowns: int
    ability_flags: int
    frostbite: int
    cute: int
    leech_source_side: int
    leech_source_slot: int
    fainted: int


class SideState(NamedTuple):
    active: int
    magic: int
    marks: int
    devotion: int
    burst_entries: int
    barrel_pending: int
    skill_counts: int
    pets: tuple[PetState, ...]
    moves: tuple[tuple[int, int, int, int], ...]


class KernelState(NamedTuple):
    turn: int
    weather: int
    rng: int
    winner: int
    side_a: SideState
    side_b: SideState


def move_choice(skill_index: int) -> Choice:
    return Choice(ACTION_MOVE, skill_index)


def switch_choice(slot_index: int) -> Choice:
    return Choice(ACTION_SWITCH, slot_index)


def pack_weather(weather: int, turns: int) -> int:
    return (weather & 0xF) | ((turns & 0xF) << 4)


def weather_type(weather: int) -> int:
    return weather & 0xF


def weather_turns(weather: int) -> int:
    return (weather >> 4) & 0xF


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
    return PetState(
        pet_id=pet_id,
        current_hp=row[1],
        current_energy=STARTING_ENERGY,
        buff_stages=_pack_buff(),
        status_flags=0,
        status_counts=0,
        cooldowns=0,
        ability_flags=hot.ABILITY_FLAGS[ability_id] if ability_id < len(hot.ABILITY_FLAGS) else 0,
        frostbite=0,
        cute=0,
        leech_source_side=-1,
        leech_source_slot=-1,
        fainted=0,
    )


def _move_row(pet_id: int, override: tuple[int, ...] | None) -> tuple[int, int, int, int]:
    ids = override if override is not None else hot.PET_SKILLS[pet_id]
    return tuple((tuple(ids) + (0, 0, 0, 0))[:4])  # type: ignore[return-value]


def make_side(pet_ids: tuple[int, ...], move_rows: tuple[tuple[int, ...], ...] | None = None) -> SideState:
    pets = tuple(_pet_state(pet_id) for pet_id in pet_ids)
    moves = tuple(_move_row(pet_id, move_rows[idx] if move_rows and idx < len(move_rows) else None)
                  for idx, pet_id in enumerate(pet_ids))
    return SideState(0, 4, 0, 0, 0, 0, 0, pets, moves)


def make_state(
    team_a: tuple[int, ...],
    team_b: tuple[int, ...],
    *,
    team_a_moves: tuple[tuple[int, ...], ...] | None = None,
    team_b_moves: tuple[tuple[int, ...], ...] | None = None,
    weather: int = WeatherType.NONE.value,
    weather_duration: int = 0,
    rng_seed: int = 1,
) -> KernelState:
    return KernelState(
        turn=0,
        weather=pack_weather(weather, weather_duration),
        rng=rng_seed & 0xFFFFFFFF,
        winner=NO_WINNER,
        side_a=make_side(team_a, team_a_moves),
        side_b=make_side(team_b, team_b_moves),
    )


def copy_state(state: KernelState) -> KernelState:
    side_a = SideState(
        state.side_a.active,
        state.side_a.magic,
        state.side_a.marks,
        state.side_a.devotion,
        state.side_a.burst_entries,
        state.side_a.barrel_pending,
        state.side_a.skill_counts,
        tuple(PetState(*pet) for pet in state.side_a.pets),
        tuple(tuple(row) for row in state.side_a.moves),
    )
    side_b = SideState(
        state.side_b.active,
        state.side_b.magic,
        state.side_b.marks,
        state.side_b.devotion,
        state.side_b.burst_entries,
        state.side_b.barrel_pending,
        state.side_b.skill_counts,
        tuple(PetState(*pet) for pet in state.side_b.pets),
        tuple(tuple(row) for row in state.side_b.moves),
    )
    return KernelState(state.turn, state.weather, state.rng, state.winner, side_a, side_b)


def replace_pet(side: SideState, slot: int, pet: PetState) -> SideState:
    pets = side.pets[:slot] + (pet,) + side.pets[slot + 1:]
    return side._replace(pets=pets)
