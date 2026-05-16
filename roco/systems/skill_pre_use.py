"""PRE_USE skill handlers — charge, energy, defense."""
from roco.engine.state import EffectFlag, StatusFlag, StatusType, BattleEvent
from roco.engine.events import GameEvent, EventCtx

def register(bus):
    def h_charge(ctx):
        sk = ctx.data.get("skill")
        if not sk or not (sk.effect_flags & EffectFlag.CHARGE): return
        ctx.actor.charging_skill = ctx.actor.persistent.moves.index(sk)
        ctx.cancelled = True
        ctx.state.log.append(BattleEvent(turn=ctx.state.turn_number, actor=ctx.actor.persistent.name, action="buff", detail={"move":sk.name,"charge":True}))
    def h_energy_all_in(ctx):
        sk = ctx.data.get("skill")
        if not sk or not (sk.effect_flags & EffectFlag.ENERGY_ALL_IN): return
        r = ctx.actor.current_energy
        if r > 0:
            ctx.power_mod += r * 0.25
            ctx.data["cost"] = r
    def h_defense(ctx):
        sk = ctx.data.get("skill")
        if not sk or sk.damage_reduction <= 0: return
        ctx.actor._defense_reduction = sk.damage_reduction
        ctx.state.log.append(BattleEvent(turn=ctx.state.turn_number, actor=ctx.actor.persistent.name, action="buff", detail={"move":sk.name,"defense":f"{sk.damage_reduction:.0%}"}))
    def h_hp_for_energy(ctx):
        sk = ctx.data.get("skill")
        if not sk or sk.hp_cost_pct <= 0: return
        ctx.actor.current_hp = max(0, ctx.actor.current_hp - int(ctx.actor.max_hp * sk.hp_cost_pct))
    bus.on(GameEvent.PRE_USE, h_charge, priority=0, source="skill")
    bus.on(GameEvent.PRE_USE, h_energy_all_in, priority=5, source="skill")
    bus.on(GameEvent.PRE_USE, h_hp_for_energy, priority=5, source="skill")
    bus.on(GameEvent.PRE_USE, h_defense, priority=8, source="skill")
