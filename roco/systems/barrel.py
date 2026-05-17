"""Barrel (木桶) subsystem — type effectiveness nullification.

When a pet with barrel_active switches out, the NEXT entering ally
gets barrel_active, nullifying all type effectiveness (eff = 1.0)
until their first action.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from roco.engine.events import EventBus


def register_barrel_stage_hooks(bus: "EventBus") -> None:
    from roco.engine.events import GameEvent, EventCtx

    def on_switch_out(ctx: EventCtx) -> None:
        """If leaving pet has barrel, set pending for team."""
        pet = ctx.actor
        from roco.engine.state import AbilityFlag
        if not pet or not pet.has_ability_flag(AbilityFlag.BARREL_ACTIVE):
            return
        team = ctx.team or "a"
        state = ctx.state
        if team == "a":
            state.barrel_pending_a = True
        else:
            state.barrel_pending_b = True

    def on_switch_in(ctx: EventCtx) -> None:
        """If barrel pending, apply to entering pet."""
        pet = ctx.actor
        if not pet:
            return
        team = ctx.team or "a"
        state = ctx.state
        pending = state.barrel_pending_a if team == "a" else state.barrel_pending_b
        if pending:
            from roco.engine.state import AbilityFlag
            pet.set_ability_flag(AbilityFlag.BARREL_ACTIVE)
            if team == "a":
                state.barrel_pending_a = False
            else:
                state.barrel_pending_b = False

    def on_before_move(ctx: EventCtx) -> None:
        """Barrel nullifies type effectiveness until first action."""
        pet = ctx.actor
        from roco.engine.state import AbilityFlag
        if not pet or not pet.has_ability_flag(AbilityFlag.BARREL_ACTIVE):
            return
        ctx.barrel = True

    def on_after_move(ctx: EventCtx) -> None:
        """Clear barrel after first action."""
        pet = ctx.actor
        from roco.engine.state import AbilityFlag
        if pet and pet.has_ability_flag(AbilityFlag.BARREL_ACTIVE):
            pet.set_ability_flag(AbilityFlag.BARREL_ACTIVE, False)

    bus.on(GameEvent.SWITCH_OUT, on_switch_out, priority=70, source="barrel")
    bus.on(GameEvent.SWITCH_IN, on_switch_in, priority=70, source="barrel")
    bus.on(GameEvent.BEFORE_MOVE, on_before_move, priority=5, source="barrel")
    bus.on(GameEvent.AFTER_MOVE, on_after_move, priority=90, source="barrel")
