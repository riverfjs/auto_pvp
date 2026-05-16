"""Burst (迸发) subsystem — entry-turn skill bonuses.

When a pet switches in, its first turn can trigger burst effects:
- Burst skills get +40 power on entry turn
- Burst skills may have reduced energy cost
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from roco.engine.events import EventBus


def register_burst_handlers(bus: "EventBus") -> None:
    from roco.engine.events import GameEvent, EventCtx

    def on_switch_in(ctx: EventCtx) -> None:
        """Record entry turn for burst tracking."""
        pet = ctx.actor
        if not pet:
            return
        team = ctx.data.get("team", "a")
        state = ctx.state
        entry = state.burst_entry_turn_a if team == "a" else state.burst_entry_turn_b
        entry[pet.name] = state.turn_number

    def on_before_move(ctx: EventCtx) -> None:
        """Burst: if this is entry turn and skill has burst tag, +40 power."""
        pet = ctx.actor
        skill = ctx.data.get("skill")
        if not pet or not skill or not skill.burst:
            return
        state = ctx.state
        team = "a" if pet in state.team_a else "b"
        entry = state.burst_entry_turn_a if team == "a" else state.burst_entry_turn_b
        if entry.get(pet.name) == state.turn_number:
            ctx.power_mod += 0.40  # +40% power on burst

    bus.on(GameEvent.SWITCH_IN, on_switch_in, priority=90, source="burst")
    bus.on(GameEvent.BEFORE_MOVE, on_before_move, priority=45, source="burst")
