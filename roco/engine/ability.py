"""Ability lifecycle engine — hooks into battle events.

Abilities are registered by name and trigger on specific timing hooks.
The engine is data-driven: adding a new ability = adding a dict entry.
"""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from roco.engine.state import PetState, BattleState


class AbilityTiming(Enum):
    ON_ENTER = "on_enter"           # pet switches in
    ON_KILL = "on_kill"             # pet KOs an enemy
    ON_FAINT = "on_faint"           # pet faints (诈死 etc.)
    ON_TAKE_HIT = "on_take_hit"     # pet takes damage
    ON_COUNTER = "on_counter"       # pet successfully counters
    PASSIVE = "passive"             # always-on passive modifier

# Ability effect function signature:
#   (pet: PetState, state: BattleState, **kwargs) -> None
AbilityFn = Callable[["PetState", "BattleState", dict], None]

# Registry: ability_name -> [(timing, fn), ...]
ABILITY_REGISTRY: dict[str, list[tuple[AbilityTiming, AbilityFn]]] = {}


def register(name: str, timing: AbilityTiming, fn: AbilityFn) -> None:
    """Register an ability effect for a given timing hook."""
    ABILITY_REGISTRY.setdefault(name, []).append((timing, fn))


def trigger(
    pet: "PetState", timing: AbilityTiming, state: "BattleState", **kwargs,
) -> None:
    """Trigger all registered ability effects for a pet at a given timing."""
    name = pet.ability_name
    if not name or name not in ABILITY_REGISTRY:
        return
    for t, fn in ABILITY_REGISTRY[name]:
        if t == timing:
            fn(pet, state, kwargs)


# ── Built-in abilities ─────────────────────────────────────────

def _fake_death(pet: "PetState", state: "BattleState", _ctx: dict) -> None:
    """诈死: no-op (handled in _handle_faint by checking ability_name)."""
    pass


def _intimidate(pet: "PetState", state: "BattleState", _ctx: dict) -> None:
    """威慑: enemy active pet atk -20% for one turn (stacked as debuff stage -2)."""
    opp_team = state.team_b if pet in state.team_a else state.team_a
    opp = opp_team[state.active_b if pet in state.team_a else state.active_a]
    opp.buff_stages["atk_phys"] = max(-6, opp.buff_stages.get("atk_phys", 0) - 2)
    opp.buff_stages["atk_mag"] = max(-6, opp.buff_stages.get("atk_mag", 0) - 2)


def _iron_fist(pet: "PetState", _state: "BattleState", _ctx: dict) -> None:
    """铁拳: physical moves deal 20% more damage (passive)."""
    pet.power_multiplier *= 1.20


def _energy_eater(pet: "PetState", _state: "BattleState", _ctx: dict) -> None:
    """食能: on kill, restore 2 energy."""
    from roco.config.constants import MAX_ENERGY
    pet.current_energy = min(MAX_ENERGY, pet.current_energy + 2)


def _photosynthesis(pet: "PetState", _state: "BattleState", _ctx: dict) -> None:
    """光合: on taking damage, recover 5% HP."""
    heal = int(pet.max_hp * 0.05)
    pet.current_hp = min(pet.max_hp, pet.current_hp + heal)


# Register built-in abilities
register("诈死", AbilityTiming.ON_FAINT, _fake_death)
register("威慑", AbilityTiming.ON_ENTER, _intimidate)
register("铁拳", AbilityTiming.PASSIVE, _iron_fist)
register("食能", AbilityTiming.ON_KILL, _energy_eater)
register("光合", AbilityTiming.ON_TAKE_HIT, _photosynthesis)
