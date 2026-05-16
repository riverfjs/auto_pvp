"""COUNTER_SUCCESS skill handlers — counter drain, energy, status, reflect, buffs."""
from roco.engine.state import EffectFlag
from roco.engine.events import GameEvent, EventCtx
from roco.engine.state import BattleEvent
from roco.engine.damage import clamp_stage
from roco.config.constants import MAX_ENERGY


def register(bus: "EventBus") -> None:
    def h_counter_effects(ctx: EventCtx) -> None:
        skill = ctx.data.get("skill")
        if not skill:
            return
        attacker = ctx.actor
        defender = ctx.target
        if not attacker or not defender:
            return

        if skill.counter_physical_drain > 0:
            heal = int(defender.current_hp * skill.counter_physical_drain)
            defender.current_hp = min(defender.max_hp, defender.current_hp + heal)
        if skill.counter_physical_energy_drain > 0:
            stolen = min(skill.counter_physical_energy_drain, attacker.current_energy)
            attacker.current_energy -= stolen
            defender.current_energy = min(MAX_ENERGY, defender.current_energy + stolen)
        if skill.counter_status_burn_stacks > 0 and not attacker.is_immune_to_status(StatusFlag.BURN):
            attacker.status_flags |= StatusFlag.BURN; attacker.status_counts["灼烧"] = attacker.status_counts.get("灼烧", 0) + skill.counter_status_burn_stacks
        if skill.counter_status_poison_stacks > 0 and not attacker.is_immune_to_status(StatusFlag.POISON):
            attacker.status_flags |= StatusFlag.POISON; attacker.status_counts["中毒"] = attacker.status_counts.get("中毒", 0) + skill.counter_status_poison_stacks
        if skill.counter_status_freeze_stacks > 0 and not attacker.is_immune_to_status(StatusFlag.FREEZE):
            attacker.status_flags |= StatusFlag.FREEZE; attacker.status_counts["冻结"] = attacker.status_counts.get("冻结", 0) + skill.counter_status_freeze_stacks
        if skill.counter_damage_reflect > 0:
            reflect = int(ctx.data.get("damage", 0) * skill.counter_damage_reflect)
            attacker.current_hp = max(0, attacker.current_hp - reflect)
            ctx.state.log.append(BattleEvent(
                turn=ctx.state.turn_number, actor=defender.name, action="attack",
                detail={"move": "reflect", "damage": reflect, "counter": True}))
        if skill.counter_physical_self_atk:
            defender.buff_stages["atk_phys"] = clamp_stage(
                defender.buff_stages.get("atk_phys", 0) + round(skill.counter_physical_self_atk / 0.10))
        if skill.counter_defense_enemy_def:
            attacker.buff_stages["def_phys"] = clamp_stage(
                attacker.buff_stages.get("def_phys", 0) - round(skill.counter_defense_enemy_def / 0.10))

    bus.on(GameEvent.COUNTER_SUCCESS, h_counter_effects, priority=50, source="skill")
