"""Skill execution — resolves damage, applies effects, handles counters."""

from __future__ import annotations

from typing import TYPE_CHECKING

from roco.engine.damage import (
    calc_attack_damage, calc_burn_damage, calc_poison_damage,
    get_type_multiplier, get_stab, can_use_skill,
    calc_energy_after_use, apply_buff_stages, clamp_stage,
)
from roco.engine.state import SkillRef, PetState, BattleEvent, BattleState
from roco.config.constants import COUNTER_DAMAGE_BONUS, MAX_ENERGY
from roco.systems.weather import weather_damage_mult
from roco.systems.marks import (
    apply_marks_to_skill_cost, apply_marks_to_attack_power,
    calc_meteor_extra_damage,
)
from roco.systems.counter import resolve_counter


def get_skill_category(pet: PetState, skill_index: int) -> str:
    """Get the category string for a skill index. Returns '' if invalid."""
    if skill_index < 0 or skill_index >= len(pet.moves):
        return ""
    return pet.moves[skill_index].category


def execute_move(
    attacker: PetState, defender: PetState,
    skill_index: int, state: BattleState,
    countered: bool = False,
) -> None:
    """Execute a single move. Handles charge, cooldown, energy, damage, and effects."""
    if skill_index < 0 or skill_index >= len(attacker.moves):
        return

    skill = attacker.moves[skill_index]

    # ── Charge resolution ──
    if attacker.charging_skill_idx >= 0:
        if attacker.charging_skill_idx < len(attacker.moves):
            skill = attacker.moves[attacker.charging_skill_idx]
            skill_index = attacker.charging_skill_idx
        attacker.charging_skill_idx = -1

    # ── Cooldown check ──
    if attacker.cooldowns.get(skill_index, 0) > 0:
        return

    # ── Energy cost (with moisture mark) ──
    team_marks = state.marks_a if attacker in state.team_a else state.marks_b
    effective_cost = apply_marks_to_skill_cost(skill.energy, team_marks)
    if not can_use_skill(attacker.current_energy, effective_cost):
        return

    # ── Damage reduction (defense skills buff self, not target) ──
    if skill.damage_reduction > 0:
        attacker.buff_stages["def_phys"] = clamp_stage(
            attacker.buff_stages.get("def_phys", 0) + 3)
        attacker.buff_stages["def_mag"] = clamp_stage(
            attacker.buff_stages.get("def_mag", 0) + 3)
        attacker.current_energy = calc_energy_after_use(
            attacker.current_energy, effective_cost)
        state.log.append(BattleEvent(
            turn=state.turn_number, actor=attacker.name,
            action="buff",
            detail={"move": skill.name, "damage_reduction": skill.damage_reduction},
        ))
        return

    # ── Charge start ──
    if "蓄力" in skill.effect:
        attacker.current_energy = calc_energy_after_use(
            attacker.current_energy, effective_cost)
        attacker.charging_skill_idx = skill_index
        state.log.append(BattleEvent(
            turn=state.turn_number, actor=attacker.name,
            action="buff", detail={"move": skill.name, "charge": True},
        ))
        return

    # ── Pay energy ──
    attacker.current_energy = calc_energy_after_use(
        attacker.current_energy, effective_cost)

    # ── Execute by category ──
    if skill.category in ("物攻", "魔攻"):
        _execute_damage(attacker, defender, skill, state, countered)
    elif skill.category == "状态":
        _execute_status(attacker, defender, skill, state)
    elif skill.category == "防御":
        _execute_defense(attacker, skill, state)

    # ── Post-execution effects (still needed for non-bus path in tests) ──
    _apply_post_effects(attacker, defender, skill, state)

    # ── Cooldown ──
    new_cd = {i: c - 1 for i, c in attacker.cooldowns.items() if c > 1}
    if "应对" in skill.effect:
        new_cd[skill_index] = 2
    attacker.cooldowns = new_cd


def _execute_damage(
    attacker: PetState, defender: PetState,
    skill: SkillRef, state: BattleState, countered: bool,
) -> None:
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

    attacker_marks = state.marks_a if attacker in state.team_a else state.marks_b
    mark_buff = apply_marks_to_attack_power(
        skill.power, skill.element, attacker_marks, attacker.element_primary)
    counter_buff = COUNTER_DAMAGE_BONUS if countered else 1.0
    env_power_mod = getattr(attacker, "_turn_power_mod", 1.0)

    damage = calc_attack_damage(
        skill.power, atk, dfn, type_mult,
        stab=stab, weather_mult=weather_mult,
        hit_count=skill.hit_count,
        power_buff=mark_buff * counter_buff * attacker.power_multiplier * env_power_mod,
    )

    # Meteor extra damage
    defender_marks = state.marks_b if defender in state.team_b else state.marks_a
    if skill.element != "幻":
        meteor = calc_meteor_extra_damage(defender_marks)
        if meteor > 0:
            damage += meteor
            state.log.append(BattleEvent(
                turn=state.turn_number, actor=attacker.name,
                action="status_tick", detail={"status": "meteor", "extra_damage": meteor},
            ))

    defender.current_hp = max(0, defender.current_hp - damage)

    state.log.append(BattleEvent(
        turn=state.turn_number, actor=attacker.name, action="attack",
        detail={
            "move": skill.name, "damage": damage, "target": defender.name,
            "type_mult": type_mult, "stab": stab, "countered": countered,
            "target_hp_pct": round(defender.hp_pct * 100, 1),
        },
    ))

    # On-hit status
    _apply_status_from_effect(attacker, defender, skill, state)


def _execute_status(
    attacker: PetState, defender: PetState,
    skill: SkillRef, state: BattleState,
) -> None:
    _apply_status_from_effect(attacker, defender, skill, state)
    _apply_stat_changes(attacker, defender, skill, state)
    state.log.append(BattleEvent(
        turn=state.turn_number, actor=attacker.name, action="attack",
        detail={"move": skill.name, "type": "status", "target": defender.name},
    ))


def _execute_defense(
    attacker: PetState, skill: SkillRef, state: BattleState,
) -> None:
    attacker.buff_stages["def_phys"] = clamp_stage(
        attacker.buff_stages.get("def_phys", 0) + 1)
    attacker.buff_stages["def_mag"] = clamp_stage(
        attacker.buff_stages.get("def_mag", 0) + 1)
    _apply_stat_changes(attacker, attacker, skill, state)
    state.log.append(BattleEvent(
        turn=state.turn_number, actor=attacker.name, action="buff",
        detail={"move": skill.name, "type": "defense"},
    ))


def _apply_status_from_effect(
    attacker: PetState, defender: PetState,
    skill: SkillRef, state: BattleState,
) -> None:
    """Apply burn/poison/freeze/leech from pre-parsed skill fields."""
    if skill.burn_stacks > 0 and not defender.is_immune_to_status("灼烧"):
        defender.status_stacks["灼烧"] = defender.status_stacks.get("灼烧", 0) + skill.burn_stacks
        state.log.append(BattleEvent(
            turn=state.turn_number, actor=attacker.name, action="status_tick",
            detail={"status": "灼烧", "stacks": skill.burn_stacks, "target": defender.name},
        ))
    if skill.poison_stacks > 0 and not defender.is_immune_to_status("中毒"):
        defender.status_stacks["中毒"] = defender.status_stacks.get("中毒", 0) + skill.poison_stacks
    if skill.freeze_stacks > 0 and not defender.is_immune_to_status("冻结"):
        defender.status_stacks["冻结"] = defender.status_stacks.get("冻结", 0) + skill.freeze_stacks
    if skill.leech_stacks > 0:
        defender.status_stacks["寄生"] = defender.status_stacks.get("寄生", 0) + skill.leech_stacks
        defender.leech_source = attacker.name


def _apply_stat_changes(
    _attacker: PetState, _defender: PetState,
    skill: SkillRef, state: BattleState,
) -> None:
    """Apply self/enemy stat buffs from parsed effect data."""
    # Self buffs
    for stat_key, field_name in [
        ("atk_phys", "self_atk"), ("atk_mag", "self_spatk"),
        ("def_phys", "self_def"), ("def_mag", "self_spdef"),
    ]:
        val = getattr(skill, field_name, 0)
        if val != 0:
            stage = clamp_stage(_attacker.buff_stages.get(stat_key, 0) + _pct_to_stage(val))
            _attacker.buff_stages[stat_key] = stage

    spd = getattr(skill, "self_speed", 0)
    if spd != 0:
        _attacker.buff_stages["speed"] = clamp_stage(
            _attacker.buff_stages.get("speed", 0) + _pct_to_stage(spd))

    # Enemy debuffs
    for stat_key, field_name in [
        ("atk_phys", "enemy_atk"), ("atk_mag", "enemy_spatk"),
        ("def_phys", "enemy_def"), ("def_mag", "enemy_spdef"),
    ]:
        val = getattr(skill, field_name, 0)
        if val != 0:
            stage = clamp_stage(_defender.buff_stages.get(stat_key, 0) - _pct_to_stage(abs(val)))
            _defender.buff_stages[stat_key] = stage

    spd_e = getattr(skill, "enemy_speed", 0)
    if spd_e != 0:
        _defender.buff_stages["speed"] = clamp_stage(
            _defender.buff_stages.get("speed", 0) - _pct_to_stage(abs(spd_e)))


def _pct_to_stage(pct: float) -> int:
    """Convert a percentage (e.g. 0.3 = 30%) to buff stages (10% per stage)."""
    return round(pct / 0.10)


def _apply_post_effects(
    attacker: PetState, defender: PetState,
    skill: SkillRef, state: BattleState,
) -> None:
    """Apply life drain, self heal, energy steal after damage is dealt."""
    # Life drain — heal for % of damage dealt
    if skill.life_drain > 0:
        # Last attack event has the damage
        last_dmg = 0
        for ev in reversed(state.log):
            if ev.actor == attacker.name and ev.action == "attack" and "damage" in ev.detail:
                last_dmg = ev.detail["damage"]
                break
        heal = int(last_dmg * skill.life_drain)
        attacker.current_hp = min(attacker.max_hp, attacker.current_hp + heal)
        if heal > 0:
            state.log.append(BattleEvent(
                turn=state.turn_number, actor=attacker.name, action="buff",
                detail={"life_drain": heal},
            ))

    # Self heal HP
    if skill.self_heal_hp > 0:
        heal = int(attacker.max_hp * skill.self_heal_hp)
        attacker.current_hp = min(attacker.max_hp, attacker.current_hp + heal)
        state.log.append(BattleEvent(
            turn=state.turn_number, actor=attacker.name, action="buff",
            detail={"heal": heal},
        ))

    # Self heal energy
    if skill.self_heal_energy > 0:
        attacker.current_energy = min(MAX_ENERGY,
            attacker.current_energy + skill.self_heal_energy)

    # Steal energy
    if skill.steal_energy > 0:
        stolen = min(skill.steal_energy, defender.current_energy)
        defender.current_energy -= stolen
        attacker.current_energy = min(MAX_ENERGY, attacker.current_energy + stolen)

    # Enemy lose energy
    if skill.enemy_lose_energy > 0:
        defender.current_energy = max(0, defender.current_energy - skill.enemy_lose_energy)

    # Leech stacks (already applied in _apply_status_from_effect if parsed;
    # this handles the case where leech_stacks was set manually e.g. by test fixtures)
    if skill.leech_stacks > 0 and "寄生" not in defender.status_stacks:
        defender.status_stacks["寄生"] = defender.status_stacks.get("寄生", 0) + skill.leech_stacks
        defender.leech_source = attacker.name


# ── Event bus registration ─────────────────────────────────────

def register_skill_handlers(bus: "EventBus") -> None:
    """Register skill-effect post-processing handlers on the event bus."""
    from roco.engine.events import GameEvent, EventCtx

    def on_after_damage(ctx: EventCtx) -> None:
        """Post-damage effects: life drain, heal, energy steal."""
        attacker = ctx.actor
        defender = ctx.target
        if not attacker or not defender:
            return
        skill_data = ctx.data.get("skill")
        if not skill_data:
            return

        # Life drain
        if skill_data.life_drain > 0:
            dmg = ctx.data.get("damage", 0)
            heal = int(dmg * skill_data.life_drain)
            attacker.current_hp = min(attacker.max_hp, attacker.current_hp + heal)

        # Self heal HP
        if skill_data.self_heal_hp > 0:
            heal = int(attacker.max_hp * skill_data.self_heal_hp)
            attacker.current_hp = min(attacker.max_hp, attacker.current_hp + heal)

        # Self heal energy
        if skill_data.self_heal_energy > 0:
            from roco.config.constants import MAX_ENERGY
            attacker.current_energy = min(MAX_ENERGY,
                attacker.current_energy + skill_data.self_heal_energy)

        # Steal energy
        if skill_data.steal_energy > 0:
            stolen = min(skill_data.steal_energy, defender.current_energy)
            defender.current_energy -= stolen
            from roco.config.constants import MAX_ENERGY
            attacker.current_energy = min(MAX_ENERGY, attacker.current_energy + stolen)

        # Enemy lose energy
        if skill_data.enemy_lose_energy > 0:
            defender.current_energy = max(0, defender.current_energy - skill_data.enemy_lose_energy)

        # Leech is applied in _apply_status_from_effect during move execution

    bus.on(GameEvent.AFTER_DAMAGE, on_after_damage, priority=60, source="skill")

    def on_force_switch(ctx: EventCtx) -> None:
        """Force switch: self-pivot (折返) — auto-switch attacker after move."""
        skill_data = ctx.data.get("skill")
        if not skill_data or not skill_data.force_switch:
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
        # Auto-switch to first alive bench
        new_idx = alive[0]
        if is_a:
            state.active_a = new_idx
        else:
            state.active_b = new_idx
        state.log.append(BattleEvent(
            turn=state.turn_number, actor=attacker.name, action="switch",
            detail={"from": attacker.name, "to": team[new_idx].name, "force": True},
        ))

    bus.on(GameEvent.AFTER_MOVE, on_force_switch, priority=50, source="skill")

    def on_before_move(ctx: EventCtx) -> None:
        """Pre-move modifiers: energy all-in, conditional power, counter reflect."""
        attacker = ctx.actor
        skill_data = ctx.data.get("skill")
        if not attacker or not skill_data:
            return

        # ── Energy all-in (全额投入): drain all energy, +25 power per point ──
        if "耗尽" in skill_data.effect or "全额" in skill_data.effect:
            remaining = attacker.current_energy
            if remaining > 0:
                # Bonus power = 25 per energy consumed
                ctx.power_mod += remaining * 0.25  # 25% per energy point
                attacker.current_energy = 0
                ctx.data["_all_in_energy"] = remaining

        # ── Conditional power: first-hit bonus ──
        if "先手" in skill_data.effect and "威力" in skill_data.effect:
            # Check if attacker is faster
            opp_team = ctx.state.team_b if attacker in ctx.state.team_a else ctx.state.team_a
            opp = opp_team[ctx.state.active_b if attacker in ctx.state.team_a else ctx.state.active_a]
            if attacker.speed >= opp.speed:
                ctx.power_mod += 0.50  # +50% power when faster

        # ── Counter power: 3x on successful counter ──
        if ctx.data.get("countered"):
            if "应对" in skill_data.effect and "威力" in skill_data.effect:
                ctx.power_mod *= 2.0  # 翻倍 on counter

    bus.on(GameEvent.BEFORE_MOVE, on_before_move, priority=40, source="skill")

    def on_weather_skill(ctx: EventCtx) -> None:
        """Skills that set weather (沙涌→sandstorm, 祈雨→rain, 冰雹/雪天→snow)."""
        skill_data = ctx.data.get("skill")
        if not skill_data:
            return
        eff = skill_data.effect
        state = ctx.state
        if "沙涌" in eff or "沙暴" in eff:
            state.weather = "sandstorm"
            state.weather_turns = 5
        elif "祈雨" in eff or "求雨" in eff:
            state.weather = "rain"
            state.weather_turns = 5
        elif "冰雹" in eff or "雪天" in eff or "暴风雪" in eff:
            state.weather = "snow"
            state.weather_turns = 5

    bus.on(GameEvent.AFTER_MOVE, on_weather_skill, priority=30, source="skill")

    def on_counter_interrupt(ctx: EventCtx) -> None:
        """Counter interrupt: only cancel if the counter-er has '打断' effect."""
        # The countered flag means the other side's move counters this one.
        # Only cancel if explicit interrupt (counter-er has 打断 keyword).
        # We check the current move's category — if it's being countered,
        # and the counter-er has an interrupt effect, cancel.
        pass  # Interrupt is contextual — handled by the counter-er's skill effect

    bus.on(GameEvent.BEFORE_MOVE, on_counter_interrupt, priority=10, source="counter")

    def on_leech_tick(ctx: EventCtx) -> None:
        """Leech tick: 8%/stack damage, heal caster."""
        state = ctx.state
        for pet in state.team_a + state.team_b:
            stacks = pet.status_stacks.get("寄生", 0)
            if stacks <= 0 or pet.is_fainted or not pet.leech_source:
                continue
            dmg = int(pet.max_hp * 0.08 * stacks)
            pet.current_hp = max(0, pet.current_hp - dmg)
            # Find caster and heal
            for team in (state.team_a, state.team_b):
                for p in team:
                    if p.name == pet.leech_source and not p.is_fainted:
                        heal = dmg
                        p.current_hp = min(p.max_hp, p.current_hp + heal)
                        break
            state.log.append(BattleEvent(
                turn=state.turn_number, actor=pet.name, action="status_tick",
                detail={"status": "寄生", "damage": dmg, "stacks": stacks},
            ))

    bus.on(GameEvent.TURN_END, on_leech_tick, priority=180, source="skill")
