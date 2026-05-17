"""Cute (萌化) subsystem — stackable persistent state.

Cute stacks persist across switches. Effects:
- Gain: +1 stack per application
- Transfer: on faint, stacks move to killer
- Lethal shield: if stacks >= 5, survive a killing blow at 1 HP
- Damage boost: +5% power per stack
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from roco.engine.events import EventBus


def register_cute_stage_hooks(bus: "EventBus") -> None:
    from roco.engine.events import GameEvent, EventCtx

    def on_kill_transfer(ctx: EventCtx) -> None:
        """On kill, transfer target's cute stacks to killer."""
        killer = ctx.actor
        target = ctx.target
        if not killer or not target:
            return
        if target.cute > 0:
            killer.cute += target.cute
            target.cute = 0

    def on_before_move(ctx: EventCtx) -> None:
        """Cute stacks give +5% power per stack."""
        pet = ctx.actor
        if not pet or pet.cute <= 0:
            return
        ctx.power_mod += pet.cute * 0.05

    def on_take_damage(ctx: EventCtx) -> None:
        """Lethal shield: if cute >= 5 and would die, survive at 1 HP."""
        pet = ctx.actor
        if not pet or pet.cute < 5:
            return
        if pet.current_hp <= 0:
            pet.current_hp = 1
            pet.cute -= 5  # consume 5 stacks

    bus.on(GameEvent.KILL, on_kill_transfer, priority=80, source="cute")
    bus.on(GameEvent.BEFORE_MOVE, on_before_move, priority=35, source="cute")
    bus.on(GameEvent.TAKE_DAMAGE, on_take_damage, priority=90, source="cute")
