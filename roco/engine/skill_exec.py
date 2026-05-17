"""Explicit move pipeline driven by compiled effect rows."""

from __future__ import annotations

from roco.config.constants import COUNTER_DAMAGE_BONUS
from roco.engine.damage import (
    calc_attack_damage,
    can_use_skill,
    energy_after_use,
    get_stab,
    get_type_multiplier,
)
from roco.engine.effect_exec import run_skill_effects
from roco.engine.effect_model import EffectFlag, Timing
from roco.engine.enums import Element, SkillCategory, WeatherType
from roco.engine.events import EventCtx, GameEvent
from roco.engine.packing import _cooldown_at, _inc_skill_count, _set_cooldown
from roco.engine.state import ActivePet, BattleEvent, BattleState, SkillData, record_event
from roco.systems.marks import apply_marks_to_attack_power, apply_marks_to_skill_cost, calc_meteor_extra_damage
from roco.systems.weather import weather_damage_mult


_bus_instance = None


def set_bus(bus) -> None:
    global _bus_instance
    _bus_instance = bus


def _get_bus():
    if _bus_instance is None:
        raise RuntimeError("EventBus not set")
    return _bus_instance


def get_skill_category(pet: ActivePet, skill_index: int) -> SkillCategory:
    if skill_index < 0 or skill_index >= len(pet.persistent.moves):
        return SkillCategory.PHYSICAL
    return pet.persistent.moves[skill_index].category


def execute_move(
    attacker: ActivePet,
    defender: ActivePet,
    skill_index: int,
    state: BattleState,
    countered: bool = False,
    *,
    team: str | None = None,
    first_strike: bool = False,
) -> int:
    moves = attacker.persistent.moves
    if skill_index < 0 or skill_index >= len(moves):
        return 0

    skill = moves[skill_index]
    if not skill.effects:
        raise ValueError(f"skill has no compiled effect rows: {skill.name}")

    if _cooldown_at(attacker.cooldowns, skill_index) > 0:
        return 0

    exec_skill = skill
    exec_index = skill_index
    if attacker.charging_skill >= 0:
        charged = attacker.charging_skill
        attacker.charging_skill = -1
        if charged < len(moves):
            exec_skill = moves[charged]
            exec_index = charged

    bus = _get_bus()
    team = team or ("a" if attacker in state.team_a else "b")
    marks = state.marks_a if team == "a" else state.marks_b
    base_cost = apply_marks_to_skill_cost(
        exec_skill.energy + attacker._cost_mod,
        marks,
        is_attack=exec_skill.category in (SkillCategory.PHYSICAL, SkillCategory.MAGICAL),
    )

    before = EventCtx(
        GameEvent.BEFORE_MOVE,
        state,
        actor=attacker,
        target=defender,
        skill=exec_skill,
        skill_index=exec_index,
        team=team,
        cost=base_cost,
        countered=countered,
        first_strike=first_strike,
    )
    bus.emit(before)
    run_skill_effects(before, Timing.BEFORE_MOVE)
    if before.cancelled:
        return 0

    cost = max(0, before.cost + before.energy_delta)
    if state.weather_type is WeatherType.SANDSTORM and exec_skill.element == "地":
        cost = cost // 2
    if not can_use_skill(attacker.current_energy, cost):
        return 0

    attacker.current_energy = energy_after_use(attacker.current_energy, cost)
    attacker._power_mod *= before.power_mod
    _record_skill_use(state, team, exec_skill)

    damage = 0
    if exec_skill.category in (SkillCategory.PHYSICAL, SkillCategory.MAGICAL):
        damage = _run_damage_pipeline(attacker, defender, exec_skill, state, countered, first_strike, bus)

    after = EventCtx(
        GameEvent.AFTER_MOVE,
        state,
        actor=attacker,
        target=defender,
        skill=exec_skill,
        skill_index=exec_index,
        team=team,
        damage=damage,
        countered=countered,
        first_strike=first_strike,
    )
    run_skill_effects(after, Timing.AFTER_MOVE)
    bus.emit(after)

    if exec_skill.effect_flags & EffectFlag.COUNTER:
        attacker.cooldowns = _set_cooldown(attacker.cooldowns, exec_index, 2)
    return damage


def _record_skill_use(state: BattleState, team: str, skill: SkillData) -> None:
    try:
        elem = Element.from_str(skill.element)
    except ValueError:
        return
    if team == "a":
        state.skill_counts_a = _inc_skill_count(state.skill_counts_a, elem)
    else:
        state.skill_counts_b = _inc_skill_count(state.skill_counts_b, elem)


def _weather_key(weather: WeatherType) -> str | None:
    return {
        WeatherType.RAIN: "rain",
        WeatherType.SANDSTORM: "sandstorm",
        WeatherType.SNOW: "snow",
    }.get(weather)


def _run_damage_pipeline(
    attacker: ActivePet,
    defender: ActivePet,
    skill: SkillData,
    state: BattleState,
    countered: bool,
    first_strike: bool,
    bus,
) -> int:
    hit = EventCtx(
        GameEvent.CHECK_HIT,
        state,
        actor=attacker,
        target=defender,
        skill=skill,
        countered=countered,
        first_strike=first_strike,
    )
    bus.emit(hit)
    run_skill_effects(hit, Timing.CHECK_HIT)
    if hit.cancelled:
        bus.emit(EventCtx(GameEvent.MOVE_MISS, state, actor=attacker, target=defender, skill=skill))
        return 0

    calc = EventCtx(
        GameEvent.CALC_DAMAGE,
        state,
        actor=attacker,
        target=defender,
        skill=skill,
        countered=countered,
        first_strike=first_strike,
        barrel=hit.barrel,
        power_bonus=attacker.next_power_bonus,
    )
    bus.emit(calc)
    run_skill_effects(calc, Timing.CALC_DAMAGE)

    base_damage, detail = _calculate_damage(attacker, defender, skill, state, countered, calc)
    adjust = EventCtx(
        GameEvent.ADJUST_DAMAGE,
        state,
        actor=attacker,
        target=defender,
        skill=skill,
        damage=base_damage,
        countered=countered,
        first_strike=first_strike,
        barrel=calc.barrel,
    )
    bus.emit(adjust)
    run_skill_effects(adjust, Timing.ADJUST_DAMAGE)
    damage = max(0, int(adjust.damage * adjust.damage_mult))

    reduction = defender._defense_reduction
    if reduction > 0 and damage > 0:
        damage = max(1, int(damage * (1.0 - reduction)))
        defender._defense_reduction = 0.0

    apply = EventCtx(
        GameEvent.APPLY_DAMAGE,
        state,
        actor=attacker,
        target=defender,
        skill=skill,
        damage=damage,
        countered=countered,
        first_strike=first_strike,
    )
    bus.emit(apply)
    run_skill_effects(apply, Timing.APPLY_DAMAGE)
    damage = max(0, int(apply.damage * apply.damage_mult))

    defender.current_hp = max(0, defender.current_hp - damage)
    if attacker.next_power_bonus or attacker.next_power_pct_bps:
        attacker.next_power_bonus = 0
        attacker.next_power_pct_bps = 0
    attacker._power_mod = 1.0

    record_event(state, BattleEvent(
        turn=state.turn_number,
        actor=attacker.persistent.name,
        action="attack",
        detail={
            "move": skill.name,
            "damage": damage,
            "target": defender.persistent.name,
            "countered": countered,
            "target_hp_pct": round(defender.hp_pct * 100, 1),
            **detail,
        },
    ))

    take = EventCtx(
        GameEvent.TAKE_DAMAGE,
        state,
        actor=defender,
        target=attacker,
        skill=skill,
        damage=damage,
        countered=countered,
        first_strike=first_strike,
    )
    bus.emit(take)
    run_skill_effects(take, Timing.TAKE_DAMAGE)
    return damage


def _calculate_damage(
    attacker: ActivePet,
    defender: ActivePet,
    skill: SkillData,
    state: BattleState,
    countered: bool,
    ctx: EventCtx,
) -> tuple[int, dict]:
    phys = skill.category == SkillCategory.PHYSICAL
    atk = float(attacker.atk_phys if phys else attacker.atk_mag)
    dfn = float(defender.def_phys if phys else defender.def_mag)
    type_mult = 1.0 if ctx.barrel else get_type_multiplier(skill.element, defender.elements)
    stab = get_stab(skill.element, attacker.elements[0])
    weather_mult = weather_damage_mult(skill.element, _weather_key(state.weather_type))
    atk_marks = state.marks_a if attacker in state.team_a else state.marks_b
    mark_buff = apply_marks_to_attack_power(
        skill.power,
        skill.element,
        atk_marks,
        attacker.elements[0],
        first_strike=ctx.first_strike,
        base_energy=skill.energy,
    )
    counter_buff = COUNTER_DAMAGE_BONUS if countered else 1.0
    power_buff = mark_buff * counter_buff * (attacker.power_mult / 100.0) * attacker._power_mod * ctx.power_mod

    power = max(0, skill.power + ctx.power_bonus)
    hit_count = max(1, int((skill.hit_count + ctx.hit_count_delta) * ctx.hit_count_mult))
    next_pct = 1.0 + attacker.next_power_pct_bps / 10000.0

    damage = calc_attack_damage(
        power,
        atk,
        dfn,
        type_mult,
        stab=stab,
        weather=weather_mult,
        hit_count=hit_count,
        power_buff=power_buff * next_pct,
    )
    dfn_marks = state.marks_b if defender in state.team_b else state.marks_a
    if skill.element != "幻":
        damage += calc_meteor_extra_damage(dfn_marks)
    damage = int(damage * ctx.damage_mult)
    return damage, {"type_mult": type_mult, "stab": stab}


def register_skill_handlers(bus) -> None:
    set_bus(bus)
    import importlib

    importlib.import_module("roco.systems.skill_leech").register(bus)
