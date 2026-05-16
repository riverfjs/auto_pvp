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
from roco.engine.state import SkillRef, PetState, BattleEvent, BattleState, EffectFlag, StatusFlag
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
    if exec_skill.effect_flags & EffectFlag.COUNTER:
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


# ── Handler registration (delegates to phase-specific modules) ──

def register_skill_handlers(bus: "EventBus") -> None:
    """Register all skill effect handlers. Each phase is a separate subsystem."""
    set_bus(bus)
    from roco.systems.skill_pre_use import register as reg_pre
    from roco.systems.skill_on_damage import register as reg_dmg
    from roco.systems.skill_post_use import register as reg_post
    from roco.systems.skill_leech import register as reg_leech
    from roco.systems.skill_counter import register as reg_ctr
    reg_pre(bus)
    reg_dmg(bus)
    reg_post(bus)
    reg_leech(bus)
    reg_ctr(bus)
