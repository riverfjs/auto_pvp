"""PRE_USE skill handlers — charge, energy mods, defense setup."""
from roco.engine.state import StatusFlag, EffectFlag
from roco.engine.events import GameEvent, EventCtx
from roco.engine.state import BattleEvent
from roco.config.constants import MAX_ENERGY


def register(bus: "EventBus") -> None:
    def h_charge(ctx: EventCtx) -> None:
        skill = ctx.data.get("skill")
        if not skill or not (skill.effect_flags & EffectFlag.CHARGE):
            return
        ctx.actor.charging_skill_idx = ctx.actor.moves.index(skill)
        ctx.cancelled = True
        ctx.state.log.append(BattleEvent(
            turn=ctx.state.turn_number, actor=ctx.actor.name,
            action="buff", detail={"move": skill.name, "charge": True}))

    def h_energy_all_in(ctx: EventCtx) -> None:
        skill = ctx.data.get("skill")
        if not skill or not (skill.effect_flags & EffectFlag.ENERGY_ALL_IN):
            return
        remaining = ctx.actor.current_energy
        if remaining > 0:
            ctx.actor._turn_power_mod = getattr(ctx.actor, "_turn_power_mod", 1.0) + remaining * 0.25
            ctx.actor.current_energy = 0

    def h_defense(ctx: EventCtx) -> None:
        skill = ctx.data.get("skill")
        if not skill or skill.damage_reduction <= 0:
            return
        ctx.actor._defense_reduction = skill.damage_reduction
        ctx.state.log.append(BattleEvent(
            turn=ctx.state.turn_number, actor=ctx.actor.name, action="buff",
            detail={"move": skill.name, "defense": f"{skill.damage_reduction:.0%}"}))

    def h_hp_for_energy(ctx: EventCtx) -> None:
        skill = ctx.data.get("skill")
        if not skill or skill.hp_cost_pct <= 0:
            return
        ctx.actor.current_hp = max(0, ctx.actor.current_hp - int(ctx.actor.max_hp * skill.hp_cost_pct))

    bus.on(GameEvent.PRE_USE, h_charge, priority=0, source="skill")
    bus.on(GameEvent.PRE_USE, h_energy_all_in, priority=5, source="skill")
    bus.on(GameEvent.PRE_USE, h_hp_for_energy, priority=5, source="skill")
    bus.on(GameEvent.PRE_USE, h_defense, priority=8, source="skill")
