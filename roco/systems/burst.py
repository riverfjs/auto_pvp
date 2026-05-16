"""Burst (迸发) subsystem — entry-turn skill bonuses.

When a pet switches in, its first turn can trigger burst effects:
- Burst skills get +40% power on entry turn
- Burst may extend via ability_state["burst_extend"]
- Burst power bonus via ability_state["burst_power_bonus"]
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from roco.engine.events import EventBus


def register_burst_handlers(bus: "EventBus") -> None:
    from roco.engine.events import GameEvent, EventCtx
    from roco.engine.state import _unpack_burst_entry, _set_burst_entry

    def on_switch_in(ctx: EventCtx) -> None:
        """Record entry turn for burst tracking, keyed by slot."""
        pet = ctx.actor
        if not pet:
            return
        team = ctx.data.get("team", "a")
        state = ctx.state
        if team == "a":
            state.burst_entry_turn_a = _set_burst_entry(
                state.burst_entry_turn_a, pet.slot, state.turn_number)
        else:
            state.burst_entry_turn_b = _set_burst_entry(
                state.burst_entry_turn_b, pet.slot, state.turn_number)

    def on_before_move(ctx: EventCtx) -> None:
        """Burst: if this is entry turn (or within burst_extend) and skill has burst tag."""
        pet = ctx.actor
        skill = ctx.data.get("skill")
        if not pet or not skill or not skill.burst:
            return
        state = ctx.state
        team = "a" if pet in state.team_a else "b"
        packed = state.burst_entry_turn_a if team == "a" else state.burst_entry_turn_b
        entry_turn = _unpack_burst_entry(packed, pet.slot)

        burst_extend = pet.ability_state.get("burst_extend", 0)
        is_burst = state.turn_number == entry_turn
        if not is_burst and burst_extend > 0:
            if state.turn_number <= entry_turn + burst_extend:
                is_burst = True

        if is_burst:
            bonus = pet.ability_state.get("burst_power_bonus", 40)
            ctx.power_mod += bonus / 100.0

            # Enemy cost up during burst
            cost_up = pet.ability_state.get("burst_enemy_cost_up", 0)
            if cost_up > 0:
                ctx.data["_burst_cost_up"] = cost_up

            # Element cost reduce
            elem_reduce = pet.ability_state.get("burst_element_cost_reduce")
            if elem_reduce:
                ctx.data["_burst_elem_reduce"] = elem_reduce

    bus.on(GameEvent.SWITCH_IN, on_switch_in, priority=90, source="burst")
    bus.on(GameEvent.BEFORE_MOVE, on_before_move, priority=45, source="burst")
