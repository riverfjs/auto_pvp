"""ON_DAMAGE handlers — drain, heal, steal, reflect."""
from roco.engine.state import EffectFlag, StatusFlag, StatusType, BattleEvent
from roco.engine.events import GameEvent, EventCtx
from roco.config.constants import MAX_ENERGY

def register(bus):
    def h_drain(ctx):
        sk = ctx.data.get("skill")
        if not sk or sk.life_drain <= 0: return
        dmg = ctx.data.get("damage", 0)
        ctx.actor.current_hp = min(ctx.actor.max_hp, ctx.actor.current_hp + int(dmg * sk.life_drain))
    def h_heal(ctx):
        sk = ctx.data.get("skill")
        if not sk: return
        if sk.self_heal_hp > 0: ctx.actor.current_hp = min(ctx.actor.max_hp, ctx.actor.current_hp + int(ctx.actor.max_hp * sk.self_heal_hp))
        if sk.self_heal_energy > 0: ctx.actor.current_energy = min(MAX_ENERGY, ctx.actor.current_energy + sk.self_heal_energy)
    def h_steal(ctx):
        sk = ctx.data.get("skill")
        if not sk: return
        if sk.steal_energy > 0:
            s = min(sk.steal_energy, ctx.target.current_energy)
            ctx.target.current_energy -= s; ctx.actor.current_energy = min(MAX_ENERGY, ctx.actor.current_energy + s)
        if sk.enemy_lose_energy > 0: ctx.target.current_energy = max(0, ctx.target.current_energy - sk.enemy_lose_energy)
    def h_mirror(ctx):
        sk = ctx.data.get("skill")
        if not sk or not ctx.data.get("countered") or not (sk.effect_flags & EffectFlag.MIRROR_DAMAGE): return
        ctx.target.current_hp = max(0, ctx.target.current_hp - sk.power)
        ctx.state.log.append(BattleEvent(turn=ctx.state.turn_number, actor=ctx.target.persistent.name, action="attack", detail={"move":"reflect","damage":sk.power,"mirror":True}))
    bus.on(GameEvent.ON_DAMAGE, h_drain, priority=20, source="skill")
    bus.on(GameEvent.ON_DAMAGE, h_heal, priority=25, source="skill")
    bus.on(GameEvent.ON_DAMAGE, h_steal, priority=30, source="skill")
    bus.on(GameEvent.ON_DAMAGE, h_mirror, priority=35, source="skill")
