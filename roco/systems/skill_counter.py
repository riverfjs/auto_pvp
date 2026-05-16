"""COUNTER_SUCCESS handlers."""
from roco.engine.state import EffectFlag, StatusFlag, StatusType, BattleEvent
from roco.engine.events import GameEvent, EventCtx
from roco.engine.damage import clamp_stage
from roco.config.constants import MAX_ENERGY

def register(bus):
    def h(ctx):
        sk = ctx.data.get("skill")
        if not sk: return
        a, d = ctx.actor, ctx.target
        if not a or not d: return
        if sk.counter_physical_drain > 0:
            d.current_hp = min(d.max_hp, d.current_hp + int(d.current_hp * sk.counter_physical_drain))
        if sk.counter_physical_energy_drain > 0:
            s = min(sk.counter_physical_energy_drain, a.current_energy)
            a.current_energy -= s; d.current_energy = min(MAX_ENERGY, d.current_energy + s)
        if sk.counter_status_burn_stacks > 0 and not a.is_immune_to(StatusFlag.BURN):
            a.status_flags |= StatusFlag.BURN; a.set_status_count(StatusType.BURN, a.get_status_count(StatusType.BURN) + sk.counter_status_burn_stacks)
        if sk.counter_status_poison_stacks > 0 and not a.is_immune_to(StatusFlag.POISON):
            a.status_flags |= StatusFlag.POISON; a.set_status_count(StatusType.POISON, a.get_status_count(StatusType.POISON) + sk.counter_status_poison_stacks)
        if sk.counter_status_freeze_stacks > 0 and not a.is_immune_to(StatusFlag.FREEZE):
            a.status_flags |= StatusFlag.FREEZE; a.set_status_count(StatusType.FREEZE, a.get_status_count(StatusType.FREEZE) + sk.counter_status_freeze_stacks)
        if sk.counter_damage_reflect > 0:
            rf = int(ctx.data.get("damage", 0) * sk.counter_damage_reflect)
            a.current_hp = max(0, a.current_hp - rf)
            ctx.state.log.append(BattleEvent(turn=ctx.state.turn_number, actor=d.persistent.name, action="attack", detail={"move":"reflect","damage":rf,"counter":True}))
        if sk.counter_physical_self_atk: d.set_buff(0, clamp_stage(d.get_buff(0) + round(sk.counter_physical_self_atk / 0.10)))
        if sk.counter_defense_enemy_def: a.set_buff(1, clamp_stage(a.get_buff(1) - round(sk.counter_defense_enemy_def / 0.10)))
    bus.on(GameEvent.COUNTER_SUCCESS, h, priority=50, source="skill")
