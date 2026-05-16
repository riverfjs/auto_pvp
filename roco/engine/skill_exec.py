"""Phase-based skill execution — event-driven, not tag-driven.

Each phase fires an event. Subsystems register handlers on the EventBus
for specific phases. Handlers check their own preconditions (skill fields).

Phases:
  PRE_USE  — charge, energy mod, defense setup (can cancel)
  ON_DAMAGE — damage calculation + application
  POST_USE — effects after damage: drain, heal, status, stat change, etc.
"""

from __future__ import annotations

from roco.engine.damage import (
    calc_attack_damage, get_type_multiplier, get_stab,
    calc_energy_after_use, can_use_skill, apply_buff_stages,
)
from roco.engine.state import SkillRef, PetState, BattleEvent, BattleState
from roco.config.constants import COUNTER_DAMAGE_BONUS, MAX_ENERGY
from roco.systems.weather import weather_damage_mult
from roco.systems.marks import (
    apply_marks_to_skill_cost, apply_marks_to_attack_power, calc_meteor_extra_damage,
)


def get_skill_category(pet: PetState, skill_index: int) -> str:
    if skill_index < 0 or skill_index >= len(pet.moves):
        return ""
    return pet.moves[skill_index].category


def execute_move(attacker: PetState, defender: PetState,
                 skill_index: int, state: BattleState,
                 countered: bool = False) -> None:
    """Phase-based skill execution. Emits events, handlers react to data fields."""
    if skill_index < 0 or skill_index >= len(attacker.moves):
        return
    skill = attacker.moves[skill_index]

    # Cooldown check
    if attacker.cooldowns.get(skill_index, 0) > 0:
        return

    # Energy check
    team_marks = state.marks_a if attacker in state.team_a else state.marks_b
    effective_cost = apply_marks_to_skill_cost(skill.energy, team_marks)
    if not can_use_skill(attacker.current_energy, effective_cost):
        return

    # Charge resolution
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

    # We need the bus — it's on the engine. Use a module-level reference.
    bus = _get_bus()

    # ── Phase: PRE_USE ──
    ctx = _emit(bus, "PRE_USE", state, attacker, defender,
                {"skill": exec_skill, "countered": countered})
    if ctx.cancelled:
        return

    # ── Phase: ON_DAMAGE (damage calculation) ──
    if exec_skill.category in ("物攻", "魔攻"):
        _calc_and_apply_damage(attacker, defender, exec_skill, state, countered, bus)

    # ── Phase: POST_USE ──
    _emit(bus, "POST_USE", state, attacker, defender,
          {"skill": exec_skill, "countered": countered})

    # Cooldown
    new_cd = {i: c - 1 for i, c in attacker.cooldowns.items() if c > 1}
    if "counter" in exec_skill.tags:
        new_cd[exec_index] = 2
    attacker.cooldowns = new_cd


# ── Internal helpers ───────────────────────────────────────────

_bus_instance: "EventBus | None" = None


def _get_bus() -> "EventBus":
    if _bus_instance is None:
        raise RuntimeError("EventBus not set — call set_bus() from BattleEngine.__init__")
    return _bus_instance


def set_bus(bus: "EventBus") -> None:
    """Called by BattleEngine.__init__ to inject the bus."""
    global _bus_instance
    _bus_instance = bus


def _emit(bus, event_name: str, state, actor, target, data) -> "EventCtx":
    from roco.engine.events import GameEvent, EventCtx
    evt = getattr(GameEvent, event_name)
    ctx = EventCtx(evt, state, actor=actor, target=target, data=data)
    bus.emit(ctx)
    return ctx


def _calc_and_apply_damage(attacker: PetState, defender: PetState,
                           skill: SkillRef, state: BattleState,
                           countered: bool, bus: "EventBus") -> None:
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

    # Defense reduction (set by PRE_USE handler)
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

    # ON_DAMAGE event for post-damage reactions (drain, steal, etc.)
    _emit(bus, "ON_DAMAGE", state, attacker, defender,
          {"skill": skill, "damage": damage, "countered": countered})


# ── Event handlers registered on the bus ───────────────────────

def register_skill_handlers(bus: "EventBus") -> None:
    """Register all skill effect handlers on phase events.
    Each handler checks its own precondition from skill data fields.
    No tag dispatch needed."""
    from roco.engine.events import GameEvent, EventCtx
    set_bus(bus)

    # ── PRE_USE handlers ──

    def h_charge(ctx: EventCtx) -> None:
        skill = ctx.data.get("skill")
        if not skill or "charge" not in skill.tags:
            return
        ctx.actor.charging_skill_idx = ctx.actor.moves.index(skill)
        ctx.cancelled = True
        ctx.state.log.append(BattleEvent(
            turn=ctx.state.turn_number, actor=ctx.actor.name,
            action="buff", detail={"move": skill.name, "charge": True},
        ))

    def h_energy_all_in(ctx: EventCtx) -> None:
        skill = ctx.data.get("skill")
        if not skill or "energy_all_in" not in skill.tags:
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
            detail={"move": skill.name, "defense": f"{skill.damage_reduction:.0%}"},
        ))

    def h_hp_for_energy(ctx: EventCtx) -> None:
        skill = ctx.data.get("skill")
        if not skill or skill.hp_cost_pct <= 0:
            return
        hp_cost = int(ctx.actor.max_hp * skill.hp_cost_pct)
        ctx.actor.current_hp = max(0, ctx.actor.current_hp - hp_cost)

    # ── ON_DAMAGE handlers ──

    def h_life_drain(ctx: EventCtx) -> None:
        skill = ctx.data.get("skill")
        if not skill or skill.life_drain <= 0:
            return
        dmg = ctx.data.get("damage", 0)
        heal = int(dmg * skill.life_drain)
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
        countered = ctx.data.get("countered", False)
        if not skill or not countered or "mirror_damage" not in skill.tags:
            return
        reflect_dmg = skill.power
        ctx.target.current_hp = max(0, ctx.target.current_hp - reflect_dmg)
        ctx.state.log.append(BattleEvent(
            turn=ctx.state.turn_number, actor=ctx.target.name, action="attack",
            detail={"move": "reflect", "damage": reflect_dmg, "mirror": True},
        ))

    # ── POST_USE handlers ──

    def h_burn(ctx: EventCtx) -> None:
        skill = ctx.data.get("skill")
        if not skill or skill.burn_stacks <= 0:
            return
        if not ctx.target.is_immune_to_status("灼烧"):
            ctx.target.status_stacks["灼烧"] = ctx.target.status_stacks.get("灼烧", 0) + skill.burn_stacks

    def h_poison(ctx: EventCtx) -> None:
        skill = ctx.data.get("skill")
        if not skill or skill.poison_stacks <= 0:
            return
        if not ctx.target.is_immune_to_status("中毒"):
            ctx.target.status_stacks["中毒"] = ctx.target.status_stacks.get("中毒", 0) + skill.poison_stacks

    def h_freeze(ctx: EventCtx) -> None:
        skill = ctx.data.get("skill")
        if not skill or skill.freeze_stacks <= 0:
            return
        if not ctx.target.is_immune_to_status("冻结"):
            ctx.target.status_stacks["冻结"] = ctx.target.status_stacks.get("冻结", 0) + skill.freeze_stacks

    def h_leech(ctx: EventCtx) -> None:
        skill = ctx.data.get("skill")
        if not skill or skill.leech_stacks <= 0:
            return
        ctx.target.status_stacks["寄生"] = ctx.target.status_stacks.get("寄生", 0) + skill.leech_stacks
        ctx.target.leech_source = ctx.actor.name

    def h_stat_change(ctx: EventCtx) -> None:
        skill = ctx.data.get("skill")
        if not skill or "stat_change" not in skill.tags:
            return
        from roco.engine.damage import clamp_stage
        for stat_key, field_name in [
            ("atk_phys", "self_atk"), ("atk_mag", "self_spatk"),
            ("def_phys", "self_def"), ("def_mag", "self_spdef"),
        ]:
            val = getattr(skill, field_name, 0)
            if val != 0:
                stage = clamp_stage(ctx.actor.buff_stages.get(stat_key, 0) + round(val / 0.10))
                ctx.actor.buff_stages[stat_key] = stage
        spd = skill.self_speed
        if spd != 0:
            ctx.actor.buff_stages["speed"] = clamp_stage(ctx.actor.buff_stages.get("speed", 0) + round(spd / 0.10))
        for stat_key, field_name in [
            ("atk_phys", "enemy_atk"), ("atk_mag", "enemy_spatk"),
            ("def_phys", "enemy_def"), ("def_mag", "enemy_spdef"),
        ]:
            val = getattr(skill, field_name, 0)
            if val != 0:
                stage = clamp_stage(ctx.target.buff_stages.get(stat_key, 0) - round(abs(val) / 0.10))
                ctx.target.buff_stages[stat_key] = stage
        if skill.enemy_speed != 0:
            ctx.target.buff_stages["speed"] = clamp_stage(ctx.target.buff_stages.get("speed", 0) - round(abs(skill.enemy_speed) / 0.10))

    def h_force_switch(ctx: EventCtx) -> None:
        skill = ctx.data.get("skill")
        if not skill or not skill.force_switch:
            return
        state = ctx.state
        team = state.team_a if ctx.actor in state.team_a else state.team_b
        is_a = team is state.team_a
        alive = [i for i, p in enumerate(team) if not p.is_fainted and p != ctx.actor]
        if not alive:
            return
        new_idx = alive[0]
        if is_a:
            state.active_a = new_idx
        else:
            state.active_b = new_idx

    def h_weather(ctx: EventCtx) -> None:
        skill = ctx.data.get("skill")
        if not skill or not skill.weather_type:
            return
        ctx.state.weather, ctx.state.weather_turns = skill.weather_type, 5

    def h_enemy_cost_up(ctx: EventCtx) -> None:
        skill = ctx.data.get("skill")
        if not skill or skill.enemy_cost_up_amount <= 0:
            return
        ctx.target._cost_mod = getattr(ctx.target, "_cost_mod", 0) + skill.enemy_cost_up_amount
        ctx.target._cost_mod_turns = 3

    def h_permanent_mod(ctx: EventCtx) -> None:
        skill = ctx.data.get("skill")
        if not skill:
            return
        if skill.permanent_hit_growth:
            skill.hit_count += skill.permanent_hit_growth
        if skill.permanent_power_growth:
            skill.power += skill.permanent_power_growth

    # ── TURN_END / leech tick ──

    def h_leech_tick(ctx: EventCtx) -> None:
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

    # ── Register all handlers on phase events ──

    # PRE_USE (priority order matters: charge must run first to cancel)
    bus.on(GameEvent.PRE_USE, h_charge, priority=0, source="skill")
    bus.on(GameEvent.PRE_USE, h_energy_all_in, priority=5, source="skill")
    bus.on(GameEvent.PRE_USE, h_hp_for_energy, priority=5, source="skill")
    bus.on(GameEvent.PRE_USE, h_defense, priority=8, source="skill")

    # ON_DAMAGE
    bus.on(GameEvent.ON_DAMAGE, h_life_drain, priority=20, source="skill")
    bus.on(GameEvent.ON_DAMAGE, h_self_heal, priority=25, source="skill")
    bus.on(GameEvent.ON_DAMAGE, h_steal_energy, priority=30, source="skill")
    bus.on(GameEvent.ON_DAMAGE, h_mirror_damage, priority=35, source="skill")

    # POST_USE
    bus.on(GameEvent.POST_USE, h_burn, priority=40, source="skill")
    bus.on(GameEvent.POST_USE, h_poison, priority=40, source="skill")
    bus.on(GameEvent.POST_USE, h_freeze, priority=40, source="skill")
    bus.on(GameEvent.POST_USE, h_leech, priority=40, source="skill")
    bus.on(GameEvent.POST_USE, h_stat_change, priority=45, source="skill")
    bus.on(GameEvent.POST_USE, h_force_switch, priority=50, source="skill")
    bus.on(GameEvent.POST_USE, h_weather, priority=55, source="skill")
    bus.on(GameEvent.POST_USE, h_enemy_cost_up, priority=50, source="skill")
    bus.on(GameEvent.POST_USE, h_permanent_mod, priority=60, source="skill")

    # TURN_END
    bus.on(GameEvent.TURN_END, h_leech_tick, priority=180, source="skill")

    # AFTER_MOVE (force switch + weather also via this)
    # Force switch already handled in POST_USE, weather in POST_USE. Keep empty.
