"""Devotion (奉献) subsystem — team-wide stackable buffs.

Devotion types: 假寐(energy_down), 飞断(power_up), 虫茧(drain),
              捆缚(poison), 虫群过境(multi_hit)
Stacks persist across switches, cannot be cleared.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from roco.engine.events import EventBus

DEVOTION_TYPES = {
    "假寐": "energy_down",     # 技能能耗-1/层
    "飞断": "power_up",        # 威力+10%/层
    "虫茧": "drain",           # 吸血+10%/层
    "捆缚": "poison",          # 附加1层中毒/层
    "虫群过境": "multi_hit",   # 连击+1/层
}


def register_devotion_handlers(bus: "EventBus") -> None:
    from roco.engine.events import GameEvent, EventCtx

    def on_before_move(ctx: EventCtx) -> None:
        """Apply devotion buffs to move execution."""
        pet = ctx.actor
        skill = ctx.data.get("skill")
        if not pet or not skill or not skill.devotion_affected:
            return
        state = ctx.state
        devo = state.devotion_a if pet in state.team_a else state.devotion_b

        for name, count in devo.items():
            dtype = DEVOTION_TYPES.get(name, "")
            if dtype == "energy_down":
                ctx.energy_delta -= count
            elif dtype == "power_up":
                ctx.power_mod += count * 0.10
            elif dtype == "multi_hit":
                skill.hit_count += count

    bus.on(GameEvent.BEFORE_MOVE, on_before_move, priority=35, source="devotion")
