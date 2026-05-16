"""ON_DAMAGE skill handlers — drain, heal, steal, reflect."""
from roco.engine.events import GameEvent, EventCtx
from roco.engine.state import BattleEvent
from roco.config.constants import MAX_ENERGY


def register(bus: "EventBus") -> None:
    def h_life_drain(ctx: EventCtx) -> None:
        skill = ctx.data.get("skill")
        if not skill or skill.life_drain <= 0:
            return
        heal = int(ctx.data.get("damage", 0) * skill.life_drain)
        ctx.actor.current_hp = min(ctx.actor.max_hp, ctx.actor.current_hp + heal)

    def h_self_heal(ctx: EventCtx) -> None:
        skill = ctx.data.get("skill")
        if not skill:
            return
        if skill.self_heal_hp > 0:
            heal = int(ctx.actor.max_hp * skill.self_heal_hp)
            ctx.actor.current_hp = min(ctx.actor.max_hp, ctx.actor.current_hp + heal)
        if skill.self_heal_energy > 0:
            ctx.actor.current_energy = min(MAX_ENERGY, ctx.actor.current_energy + skill.self_heal_energy)

    def h_steal_energy(ctx: EventCtx) -> None:
        skill = ctx.data.get("skill")
        if not skill:
            return
        if skill.steal_energy > 0:
            stolen = min(skill.steal_energy, ctx.target.current_energy)
            ctx.target.current_energy -= stolen
            ctx.actor.current_energy = min(MAX_ENERGY, ctx.actor.current_energy + stolen)
        if skill.enemy_lose_energy > 0:
            ctx.target.current_energy = max(0, ctx.target.current_energy - skill.enemy_lose_energy)

    def h_mirror_damage(ctx: EventCtx) -> None:
        skill = ctx.data.get("skill")
        if not skill or not ctx.data.get("countered") or "mirror_damage" not in skill.tags:
            return
        reflect_dmg = skill.power
        ctx.target.current_hp = max(0, ctx.target.current_hp - reflect_dmg)
        ctx.state.log.append(BattleEvent(
            turn=ctx.state.turn_number, actor=ctx.target.name, action="attack",
            detail={"move": "reflect", "damage": reflect_dmg, "mirror": True}))

    bus.on(GameEvent.ON_DAMAGE, h_life_drain, priority=20, source="skill")
    bus.on(GameEvent.ON_DAMAGE, h_self_heal, priority=25, source="skill")
    bus.on(GameEvent.ON_DAMAGE, h_steal_energy, priority=30, source="skill")
    bus.on(GameEvent.ON_DAMAGE, h_mirror_damage, priority=35, source="skill")
