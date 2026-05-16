"""Tag-driven skill execution — each tag maps to a handler function.

Ordered execution: tags execute in priority order defined by TAG_ORDER.
All handlers are pure ((PetState, PetState, SkillRef, ...) -> side effects).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from roco.engine.damage import (
    calc_attack_damage, get_type_multiplier, get_stab,
    calc_energy_after_use, can_use_skill, apply_buff_stages, clamp_stage,
)
from roco.engine.state import SkillRef, PetState, BattleEvent, BattleState
from roco.config.constants import COUNTER_DAMAGE_BONUS, MAX_ENERGY
from roco.systems.weather import weather_damage_mult
from roco.systems.marks import (
    apply_marks_to_skill_cost, apply_marks_to_attack_power, calc_meteor_extra_damage,
)

if TYPE_CHECKING:
    pass

# Handler signature
SkillHandler = Callable[["PetState", "PetState", SkillRef, "BattleState", bool], None]

# ── Tag execution order (lower = earlier) ──────────────────────

TAG_ORDER: dict[str, int] = {
    "charge":        0,
    "energy_all_in": 5,
    "defense":       10,
    "pure_damage":   15,
    "drain":         20,
    "heal_hp":       25,
    "heal_energy":   25,
    "steal_energy":  30,
    "burn":          35,
    "poison":        35,
    "freeze":        35,
    "leech":         35,
    "stat_change":   40,
    "force_switch":  45,
    "weather":       50,
    "counter":       55,
    "conditional":   60,
    "scaling":       65,
    "multi_hit":     -1,  # handled in damage formula
    "priority":      -1,  # handled in speed calc
}

# ── Handlers ────────────────────────────────────────────────────

def _exec_charge(attacker: PetState, _defender: PetState,
                 skill: SkillRef, state: BattleState, _countered: bool) -> None:
    """Charge: skip execution this turn, auto-execute next turn."""
    attacker.charging_skill_idx = attacker.moves.index(skill)
    state.log.append(BattleEvent(
        turn=state.turn_number, actor=attacker.name,
        action="buff", detail={"move": skill.name, "charge": True},
    ))


def _exec_energy_all_in(attacker: PetState, _defender: PetState,
                        _skill: SkillRef, _state: BattleState, _countered: bool) -> None:
    """Drain all energy, add power bonus (25% per energy)."""
    remaining = attacker.current_energy
    if remaining > 0:
        attacker._turn_power_mod = getattr(attacker, "_turn_power_mod", 1.0) + remaining * 0.25
        attacker.current_energy = 0


def _exec_defense(attacker: PetState, _defender: PetState,
                  skill: SkillRef, state: BattleState, _countered: bool) -> None:
    """Defense: apply % damage reduction on damage taken this turn, or +3 def stages."""
    if skill.damage_reduction > 0:
        # Store reduction for the damage handler to apply when taking hits
        attacker._defense_reduction = skill.damage_reduction
        state.log.append(BattleEvent(
            turn=state.turn_number, actor=attacker.name, action="buff",
            detail={"move": skill.name, "defense": f"{skill.damage_reduction:.0%}"},
        ))
    else:
        attacker.buff_stages["def_phys"] = clamp_stage(attacker.buff_stages.get("def_phys", 0) + 1)
        attacker.buff_stages["def_mag"] = clamp_stage(attacker.buff_stages.get("def_mag", 0) + 1)


def _exec_pure_damage(attacker: PetState, defender: PetState,
                      skill: SkillRef, state: BattleState, countered: bool) -> None:
    """Calculate and apply attack damage with full formula."""
    phys = skill.category == "物攻"
    atk = float(attacker.effective_stats["atk_phys" if phys else "atk_mag"])
    dfn = float(defender.effective_stats["def_phys" if phys else "def_mag"])

    if attacker.buff_stages:
        buffed = apply_buff_stages(attacker.effective_stats, attacker.buff_stages)
        atk = float(buffed["atk_phys" if phys else "atk_mag"])
    if defender.buff_stages:
        buffed = apply_buff_stages(defender.effective_stats, defender.buff_stages)
        dfn = float(buffed["def_phys" if phys else "def_mag"])

    type_mult = get_type_multiplier(skill.element, defender.defender_types)
    stab = get_stab(skill.element, attacker.element_primary)
    weather_mult = weather_damage_mult(skill.element, state.weather)

    atk_marks = state.marks_a if attacker in state.team_a else state.marks_b
    mark_buff = apply_marks_to_attack_power(skill.power, skill.element, atk_marks, attacker.element_primary)
    counter_buff = COUNTER_DAMAGE_BONUS if countered else 1.0
    env_mod = getattr(attacker, "_turn_power_mod", 1.0)

    damage = calc_attack_damage(
        skill.power, atk, dfn, type_mult,
        stab=stab, weather_mult=weather_mult, hit_count=skill.hit_count,
        power_buff=mark_buff * counter_buff * attacker.power_multiplier * env_mod,
    )

    # Meteor extra damage
    dfn_marks = state.marks_b if defender in state.team_b else state.marks_a
    if skill.element != "幻":
        meteor = calc_meteor_extra_damage(dfn_marks)
        if meteor > 0:
            damage += meteor

    # % damage reduction on TAKEN damage (from defense skills on the defender)
    reduction = getattr(defender, "_defense_reduction", 0.0)
    if reduction > 0:
        damage = max(1, int(damage * (1.0 - reduction)))
        defender._defense_reduction = 0.0

    defender.current_hp = max(0, defender.current_hp - damage)

    state.log.append(BattleEvent(
        turn=state.turn_number, actor=attacker.name, action="attack",
        detail={"move": skill.name, "damage": damage, "target": defender.name,
                "type_mult": type_mult, "stab": stab, "countered": countered,
                "target_hp_pct": round(defender.hp_pct * 100, 1)},
    ))


def _exec_drain(attacker: PetState, _defender: PetState,
                skill: SkillRef, state: BattleState, _countered: bool) -> None:
    """Life drain: heal for % of last damage dealt."""
    if skill.life_drain <= 0:
        return
    last_dmg = 0
    for ev in reversed(state.log):
        if ev.actor == attacker.name and ev.action == "attack" and "damage" in ev.detail:
            last_dmg = ev.detail["damage"]
            break
    heal = int(last_dmg * skill.life_drain)
    attacker.current_hp = min(attacker.max_hp, attacker.current_hp + heal)


def _exec_self_heal(attacker: PetState, _defender: PetState,
                    skill: SkillRef, _state: BattleState, _countered: bool) -> None:
    if skill.self_heal_hp > 0:
        heal = int(attacker.max_hp * skill.self_heal_hp)
        attacker.current_hp = min(attacker.max_hp, attacker.current_hp + heal)
    if skill.self_heal_energy > 0:
        attacker.current_energy = min(MAX_ENERGY, attacker.current_energy + skill.self_heal_energy)


def _exec_steal_energy(attacker: PetState, defender: PetState,
                       skill: SkillRef, _state: BattleState, _countered: bool) -> None:
    if skill.steal_energy > 0:
        stolen = min(skill.steal_energy, defender.current_energy)
        defender.current_energy -= stolen
        attacker.current_energy = min(MAX_ENERGY, attacker.current_energy + stolen)
    if skill.enemy_lose_energy > 0:
        defender.current_energy = max(0, defender.current_energy - skill.enemy_lose_energy)


def _exec_burn(attacker: PetState, defender: PetState,
               skill: SkillRef, state: BattleState, _countered: bool) -> None:
    if not defender.is_immune_to_status("灼烧") and skill.burn_stacks > 0:
        defender.status_stacks["灼烧"] = defender.status_stacks.get("灼烧", 0) + skill.burn_stacks
        state.log.append(BattleEvent(
            turn=state.turn_number, actor=attacker.name, action="status_tick",
            detail={"status": "灼烧", "stacks": skill.burn_stacks, "target": defender.name},
        ))


def _exec_poison(attacker: PetState, defender: PetState,
                 skill: SkillRef, state: BattleState, _countered: bool) -> None:
    if not defender.is_immune_to_status("中毒") and skill.poison_stacks > 0:
        defender.status_stacks["中毒"] = defender.status_stacks.get("中毒", 0) + skill.poison_stacks


def _exec_freeze(attacker: PetState, defender: PetState,
                 skill: SkillRef, state: BattleState, _countered: bool) -> None:
    if not defender.is_immune_to_status("冻结") and skill.freeze_stacks > 0:
        defender.status_stacks["冻结"] = defender.status_stacks.get("冻结", 0) + skill.freeze_stacks


def _exec_leech(attacker: PetState, defender: PetState,
                skill: SkillRef, _state: BattleState, _countered: bool) -> None:
    if skill.leech_stacks > 0:
        defender.status_stacks["寄生"] = defender.status_stacks.get("寄生", 0) + skill.leech_stacks
        defender.leech_source = attacker.name


def _exec_stat_change(attacker: PetState, defender: PetState,
                      skill: SkillRef, _state: BattleState, _countered: bool) -> None:
    """Apply self/enemy stat buffs from parsed effect data."""
    for stat_key, field_name in [
        ("atk_phys", "self_atk"), ("atk_mag", "self_spatk"),
        ("def_phys", "self_def"), ("def_mag", "self_spdef"),
    ]:
        val = getattr(skill, field_name, 0)
        if val != 0:
            stage = clamp_stage(attacker.buff_stages.get(stat_key, 0) + round(val / 0.10))
            attacker.buff_stages[stat_key] = stage
    spd = skill.self_speed
    if spd != 0:
        attacker.buff_stages["speed"] = clamp_stage(attacker.buff_stages.get("speed", 0) + round(spd / 0.10))
    for stat_key, field_name in [
        ("atk_phys", "enemy_atk"), ("atk_mag", "enemy_spatk"),
        ("def_phys", "enemy_def"), ("def_mag", "enemy_spdef"),
    ]:
        val = getattr(skill, field_name, 0)
        if val != 0:
            stage = clamp_stage(defender.buff_stages.get(stat_key, 0) - round(abs(val) / 0.10))
            defender.buff_stages[stat_key] = stage
    if skill.enemy_speed != 0:
        defender.buff_stages["speed"] = clamp_stage(defender.buff_stages.get("speed", 0) - round(abs(skill.enemy_speed) / 0.10))


def _exec_force_switch(attacker: PetState, _defender: PetState,
                       _skill: SkillRef, state: BattleState, _countered: bool) -> None:
    """Self-pivot after move: switch to first alive bench."""
    team = state.team_a if attacker in state.team_a else state.team_b
    is_a = team is state.team_a
    alive = [i for i, p in enumerate(team) if not p.is_fainted and p != attacker]
    if not alive:
        return
    new_idx = alive[0]
    if is_a:
        state.active_a = new_idx
    else:
        state.active_b = new_idx
    state.log.append(BattleEvent(
        turn=state.turn_number, actor=attacker.name, action="switch",
        detail={"from": attacker.name, "to": team[new_idx].name, "force": True},
    ))


def _exec_set_weather(_attacker: PetState, _defender: PetState,
                      skill: SkillRef, state: BattleState, _countered: bool) -> None:
    eff = skill.effect
    if "沙涌" in eff or "沙暴" in eff:
        state.weather, state.weather_turns = "sandstorm", 5
    elif "祈雨" in eff or "求雨" in eff:
        state.weather, state.weather_turns = "rain", 5
    elif "冰雹" in eff or "雪天" in eff or "暴风雪" in eff:
        state.weather, state.weather_turns = "snow", 5


def _exec_counter_effect(attacker: PetState, _defender: PetState,
                         _skill: SkillRef, _state: BattleState, countered: bool) -> None:
    """Counter tag: mark for counter success effects (interrupt, power boost)."""
    if countered:
        attacker.power_multiplier *= 1.0  # power boost handled in damage via counter_buff


def _exec_conditional(_attacker: PetState, _defender: PetState,
                      _skill: SkillRef, _state: BattleState, _countered: bool) -> None:
    """Conditional effects are resolved at event time via BEFORE_MOVE handlers."""
    pass


def _exec_scaling(_attacker: PetState, _defender: PetState,
                  _skill: SkillRef, _state: BattleState, _countered: bool) -> None:
    """Scaling effects are resolved at event time via BEFORE_MOVE handlers."""
    pass


# ── Tag → handler map ──────────────────────────────────────────

TAG_HANDLERS: dict[str, SkillHandler] = {
    "charge":        _exec_charge,
    "energy_all_in": _exec_energy_all_in,
    "defense":       _exec_defense,
    "pure_damage":   _exec_pure_damage,
    "drain":         _exec_drain,
    "heal_hp":       _exec_self_heal,
    "heal_energy":   _exec_self_heal,
    "steal_energy":  _exec_steal_energy,
    "burn":          _exec_burn,
    "poison":        _exec_poison,
    "freeze":        _exec_freeze,
    "leech":         _exec_leech,
    "stat_change":   _exec_stat_change,
    "force_switch":  _exec_force_switch,
    "weather":       _exec_set_weather,
    "counter":       _exec_counter_effect,
    "conditional":   _exec_conditional,
    "scaling":       _exec_scaling,
}


# ── Main dispatch ──────────────────────────────────────────────

def execute_move(attacker: PetState, defender: PetState,
                 skill_index: int, state: BattleState,
                 countered: bool = False) -> None:
    """Tag-driven skill execution. Dispatches to handlers by tag order."""
    if skill_index < 0 or skill_index >= len(attacker.moves):
        return
    skill = attacker.moves[skill_index]

    # Cooldown check
    if attacker.cooldowns.get(skill_index, 0) > 0:
        return

    # Energy check (with mark cost reduction)
    team_marks = state.marks_a if attacker in state.team_a else state.marks_b
    effective_cost = apply_marks_to_skill_cost(skill.energy, team_marks)
    if not can_use_skill(attacker.current_energy, effective_cost):
        return

    # Charge resolution: if charging from last turn, auto-execute stored skill
    exec_skill = skill
    exec_index = skill_index
    if attacker.charging_skill_idx >= 0:
        ci = attacker.charging_skill_idx
        attacker.charging_skill_idx = -1
        if ci < len(attacker.moves):
            exec_skill = attacker.moves[ci]
            exec_index = ci

    # Pay energy
    attacker.current_energy = calc_energy_after_use(attacker.current_energy, effective_cost)

    # Sort tags by execution order, remove handled-elsewhere tags
    ordered = sorted(
        [t for t in exec_skill.tags if t in TAG_ORDER],
        key=lambda t: TAG_ORDER.get(t, 99),
    )

    # Execute each tag's handler
    for tag in ordered:
        handler = TAG_HANDLERS.get(tag)
        if handler:
            handler(attacker, defender, exec_skill, state, countered)

    # Cooldown
    new_cd = {i: c - 1 for i, c in attacker.cooldowns.items() if c > 1}
    if "应对" in exec_skill.effect:
        new_cd[exec_index] = 2
    attacker.cooldowns = new_cd


def get_skill_category(pet: PetState, skill_index: int) -> str:
    if skill_index < 0 or skill_index >= len(pet.moves):
        return ""
    return pet.moves[skill_index].category


def register_skill_handlers(bus: "EventBus") -> None:
    """Register skill-related event handlers on the bus."""
    from roco.engine.events import GameEvent, EventCtx
    from roco.config.constants import MAX_ENERGY

    def on_leech_tick(ctx: EventCtx) -> None:
        state = ctx.state
        for pet in state.team_a + state.team_b:
            stacks = pet.status_stacks.get("寄生", 0)
            if stacks <= 0 or pet.is_fainted or not pet.leech_source:
                continue
            dmg = int(pet.max_hp * 0.08 * stacks)
            pet.current_hp = max(0, pet.current_hp - dmg)
            for team in (state.team_a, state.team_b):
                for p in team:
                    if p.name == pet.leech_source and not p.is_fainted:
                        p.current_hp = min(p.max_hp, p.current_hp + dmg)
                        break
            state.log.append(BattleEvent(
                turn=state.turn_number, actor=pet.name, action="status_tick",
                detail={"status": "寄生", "damage": dmg, "stacks": stacks},
            ))

    def on_force_switch(ctx: EventCtx) -> None:
        skill = ctx.data.get("skill")
        if not skill or not skill.force_switch:
            return
        attacker = ctx.actor
        if not attacker or attacker.is_fainted:
            return
        state = ctx.state
        team = state.team_a if attacker in state.team_a else state.team_b
        is_a = team is state.team_a
        alive = [i for i, p in enumerate(team) if not p.is_fainted and p != attacker]
        if not alive:
            return
        new_idx = alive[0]
        if is_a:
            state.active_a = new_idx
        else:
            state.active_b = new_idx
        state.log.append(BattleEvent(
            turn=state.turn_number, actor=attacker.name, action="switch",
            detail={"from": attacker.name, "to": team[new_idx].name, "force": True},
        ))

    def on_weather_skill(ctx: EventCtx) -> None:
        skill = ctx.data.get("skill")
        if not skill:
            return
        eff = skill.effect
        state = ctx.state
        if "沙涌" in eff or "沙暴" in eff:
            state.weather, state.weather_turns = "sandstorm", 5
        elif "祈雨" in eff or "求雨" in eff:
            state.weather, state.weather_turns = "rain", 5
        elif "冰雹" in eff or "雪天" in eff or "暴风雪" in eff:
            state.weather, state.weather_turns = "snow", 5

    bus.on(GameEvent.TURN_END, on_leech_tick, priority=180, source="skill")
    bus.on(GameEvent.AFTER_MOVE, on_force_switch, priority=50, source="skill")
    bus.on(GameEvent.AFTER_MOVE, on_weather_skill, priority=30, source="skill")
