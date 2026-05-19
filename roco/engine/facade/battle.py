"""Public battle facade backed by the fixed integer kernel."""

from __future__ import annotations

from roco.common.constants import DEFAULT_MAX_TURNS
from roco.engine.generated import catalog_debug as debug
from roco.engine.generated import catalog_hot as hot
from roco.engine.common.choices import NO_WINNER, SIDE_A, SIDE_B, WIN_A, WIN_B, WIN_DRAW, Choice
from roco.engine.kernel.mechanics import update
from roco.engine.kernel.state import (
    KernelState,
    PetState,
    SideState,
    make_state,
)


class BattleEngine:
    """Thin owner for fixed-kernel state.

    Names and display lookup stay at this facade/debug boundary. Battle turns
    themselves run through ``roco.engine.kernel.mechanics.update`` over integer ids.
    """

    def __init__(self, state: KernelState, *, max_turns: int = DEFAULT_MAX_TURNS):
        self.state = state
        self.max_turns = max_turns

    @classmethod
    def from_team_ids(
        cls,
        team_a: tuple[int, ...],
        team_b: tuple[int, ...],
        *,
        team_a_moves: tuple[tuple[int, ...], ...] | None = None,
        team_b_moves: tuple[tuple[int, ...], ...] | None = None,
        team_a_bloodlines: tuple[int, ...] | None = None,
        team_b_bloodlines: tuple[int, ...] | None = None,
        team_a_bloodline_magic_id: int = 1,
        team_b_bloodline_magic_id: int = 1,
        rng_seed: int = 1,
        max_turns: int = DEFAULT_MAX_TURNS,
    ) -> "BattleEngine":
        return cls(
            make_state(
                team_a,
                team_b,
                team_a_moves=team_a_moves,
                team_b_moves=team_b_moves,
                team_a_bloodlines=team_a_bloodlines,
                team_b_bloodlines=team_b_bloodlines,
                team_a_bloodline_magic_id=team_a_bloodline_magic_id,
                team_b_bloodline_magic_id=team_b_bloodline_magic_id,
                rng_seed=rng_seed,
            ),
            max_turns=max_turns,
        )

    @classmethod
    def from_names(
        cls,
        team_a: tuple[str, ...],
        team_b: tuple[str, ...],
        *,
        team_a_moves: tuple[tuple[str, ...], ...] | None = None,
        team_b_moves: tuple[tuple[str, ...], ...] | None = None,
        rng_seed: int = 1,
        max_turns: int = DEFAULT_MAX_TURNS,
    ) -> "BattleEngine":
        return cls.from_team_ids(
            tuple(_pet_id(name) for name in team_a),
            tuple(_pet_id(name) for name in team_b),
            team_a_moves=_skill_rows(team_a_moves),
            team_b_moves=_skill_rows(team_b_moves),
            rng_seed=rng_seed,
            max_turns=max_turns,
        )

    def step(self, choice_a: Choice, choice_b: Choice) -> KernelState:
        if self.is_finished():
            return self.state
        result = update(self.state, choice_a, choice_b)
        state = result.state
        if state.winner == NO_WINNER and state.turn >= self.max_turns:
            state = state._replace(winner=WIN_DRAW)
        self.state = state
        return self.state

    def is_finished(self) -> bool:
        return self.state.winner != NO_WINNER or self.state.turn >= self.max_turns

    def get_winner(self) -> str | None:
        if self.state.winner == WIN_A:
            return "a"
        if self.state.winner == WIN_B:
            return "b"
        if self.state.winner == WIN_DRAW or (self.state.turn >= self.max_turns and self.state.winner == NO_WINNER):
            return "draw"
        return None

    def side(self, side_id: int) -> SideState:
        return self.state.side_a if side_id == SIDE_A else self.state.side_b

    def active_pet(self, side_id: int) -> PetState:
        side = self.side(side_id)
        return side.pets[side.active]

    def get_active_slot(self, side_id: int) -> int:
        return self.side(side_id).active

    def get_valid_moves(self, side_id: int) -> tuple[int, ...]:
        side = self.side(side_id)
        moves = side.moves[side.active]
        valid: list[int] = []
        for idx, skill_id in enumerate(moves):
            if skill_id > 0:
                valid.append(idx)
        return tuple(valid)

    def get_available_switches(self, side_id: int) -> tuple[int, ...]:
        side = self.side(side_id)
        return tuple(
            idx
            for idx, pet in enumerate(side.pets)
            if idx != side.active and pet.fainted == 0
        )


def _pet_id(name: str) -> int:
    try:
        return debug.PET_IDS_BY_NAME[name]
    except KeyError as exc:
        raise ValueError(f"unknown pet name: {name}") from exc


def _skill_id(name: str) -> int:
    try:
        return debug.SKILL_IDS_BY_NAME[name]
    except KeyError as exc:
        raise ValueError(f"unknown skill name: {name}") from exc


def _skill_rows(rows: tuple[tuple[str, ...], ...] | None) -> tuple[tuple[int, ...], ...] | None:
    if rows is None:
        return None
    return tuple(tuple(_skill_id(name) for name in row) for row in rows)
