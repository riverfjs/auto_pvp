"""Ability system — registers per-pet handlers on the EventBus.

Abilities are defined as (GameEvent, handler_fn) tuples and registered
when a pet enters battle. This is fully data-driven — adding a new ability
just requires adding a dict entry.

Architecture:
  ABILITY_DB[name] = [(event_type, handler_fn), ...]
  When a pet switches in, register_ability(bus, pet) hooks them up.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from roco.engine.events import EventBus, EventCtx
    from roco.engine.state import PetState

# Handler: (EventCtx, pet: PetState) -> None
AbilityFn = Callable[["EventCtx", "PetState"], None]


# ── Built-in abilities ─────────────────────────────────────────

def _fake_death(ctx: "EventCtx", pet: "PetState") -> None:
    """诈死: no-op — magic cost handled in engine._on_faint_magic by checking ability_name."""
    pass


def _intimidate(ctx: "EventCtx", pet: "PetState") -> None:
    """威慑: on enter, reduce enemy active atk/mag by 2 stages."""
    state = ctx.state
    opp_team = state.team_b if pet in state.team_a else state.team_a
    opp = opp_team[state.active_b if pet in state.team_a else state.active_a]
    opp.buff_stages["atk_phys"] = max(-6, opp.buff_stages.get("atk_phys", 0) - 2)
    opp.buff_stages["atk_mag"] = max(-6, opp.buff_stages.get("atk_mag", 0) - 2)


def _iron_fist(ctx: "EventCtx", pet: "PetState") -> None:
    """铁拳: on enter, physical moves deal 20% more (passive multiplier)."""
    pet.power_multiplier *= 1.20


def _energy_eater(ctx: "EventCtx", pet: "PetState") -> None:
    """食能: on kill, restore 2 energy."""
    from roco.config.constants import MAX_ENERGY
    pet.current_energy = min(MAX_ENERGY, pet.current_energy + 2)


def _photosynthesis(ctx: "EventCtx", pet: "PetState") -> None:
    """光合: on taking damage, recover 5% HP."""
    heal = int(pet.max_hp * 0.05)
    pet.current_hp = min(pet.max_hp, pet.current_hp + heal)


# ── Ability database ───────────────────────────────────────────

ABILITY_DB: dict[str, list[tuple]] = {
    "诈死": [("FAINT", _fake_death)],
    "威慑": [("SWITCH_IN", _intimidate)],
    "铁拳": [("SWITCH_IN", _iron_fist)],
    "食能": [("KILL", _energy_eater)],
    "光合": [("TAKE_DAMAGE", _photosynthesis)],
}


# ── Registration ───────────────────────────────────────────────

def register_ability_handlers(bus: "EventBus", pet: "PetState") -> None:
    """Register all ability handlers for a pet on the event bus."""
    from roco.engine.events import GameEvent

    name = pet.ability_name
    if not name or name not in ABILITY_DB:
        return

    event_map = {e.name: e for e in GameEvent}
    for evt_name, fn in ABILITY_DB[name]:
        evt = event_map.get(evt_name)
        if evt:
            # Capture pet in closure
            def handler(ctx: EventCtx, pet=pet, fn=fn) -> None:
                fn(ctx, pet)
            bus.on(evt, handler, priority=100, source=f"ability:{name}")
