"""Phase-based skill execution — works with ActivePet and packed bitfields."""

from __future__ import annotations

from roco.engine.damage import (
    calc_attack_damage, get_type_multiplier, get_stab,
    energy_after_use, can_use_skill,
)
from roco.engine.state import (
    ActivePet, SkillData, SkillCategory, BattleEvent, BattleState,
    EffectFlag, WeatherType, Element,
    _pack_cooldown, _unpack_cooldown, _inc_skill_count,
)
from roco.config.constants import COUNTER_DAMAGE_BONUS, MAX_ENERGY
from roco.systems.weather import weather_damage_mult
from roco.systems.marks import apply_marks_to_skill_cost, apply_marks_to_attack_power, calc_meteor_extra_damage


def get_skill_category(pet: ActivePet, skill_index: int) -> SkillCategory:
    if skill_index < 0 or skill_index >= len(pet.persistent.moves):
        return SkillCategory.PHYSICAL
    return pet.persistent.moves[skill_index].category


_bus_instance = None
def set_bus(bus): global _bus_instance; _bus_instance = bus
def _get_bus():
    if _bus_instance is None: raise RuntimeError("EventBus not set")
    return _bus_instance


def _emit(bus, event_name, state, actor, target, data):
    from roco.engine.events import GameEvent, EventCtx
    return bus.emit(EventCtx(getattr(GameEvent, event_name), state, actor=actor, target=target, data=data))


def execute_move(
    attacker: ActivePet,
    defender: ActivePet,
    skill_index: int,
    state: BattleState,
    countered: bool = False,
    *,
    team: str | None = None,
):
    moves = attacker.persistent.moves
    if skill_index < 0 or skill_index >= len(moves): return 0
    skill = moves[skill_index]

    cds = _unpack_cooldown(attacker.cooldowns)
    if cds.get(skill_index, 0) > 0: return 0

    exec_skill = skill; exec_index = skill_index
    if attacker.charging_skill >= 0:
        ci = attacker.charging_skill; attacker.charging_skill = -1
        if ci < len(moves): exec_skill = moves[ci]; exec_index = ci

    bus = _get_bus()
    team = team or ("a" if attacker in state.team_a else "b")
    marks = state.marks_a if team == "a" else state.marks_b
    base_cost = apply_marks_to_skill_cost(exec_skill.energy + attacker._cost_mod, marks)

    ctx = _emit(bus, "PRE_USE", state, attacker, defender,
                {"skill": exec_skill, "countered": countered, "skill_index": exec_index,
                 "team": team, "cost": base_cost})
    if ctx.cancelled: return 0
    cost = max(0, int(ctx.data.get("cost", base_cost)) + ctx.energy_delta)
    if not can_use_skill(attacker.current_energy, cost): return 0

    attacker.current_energy = energy_after_use(attacker.current_energy, cost)
    attacker._power_mod *= ctx.power_mod
    _record_skill_use(state, team, exec_skill)

    damage = 0
    if exec_skill.category in (SkillCategory.PHYSICAL, SkillCategory.MAGICAL):
        damage = _calc_and_apply(attacker, defender, exec_skill, state, countered, bus, ctx.data)

    _emit(bus, "POST_USE", state, attacker, defender,
          {"skill": exec_skill, "countered": countered, "damage": damage, "team": team})

    if exec_skill.effect_flags & EffectFlag.COUNTER:
        cds[exec_index] = 2
    attacker.cooldowns = _pack_cooldown(cds)
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


def _calc_and_apply(attacker: ActivePet, defender: ActivePet,
                    skill: SkillData, state: BattleState, countered: bool, bus,
                    pipeline_data: dict) -> int:
    phys = skill.category == SkillCategory.PHYSICAL
    atk = float(attacker.atk_phys if phys else attacker.atk_mag)
    dfn = float(defender.def_phys if phys else defender.def_mag)

    type_mult = 1.0 if pipeline_data.get("_barrel") else get_type_multiplier(skill.element, defender.elements)
    stab = get_stab(skill.element, attacker.elements[0])
    weather_mult = weather_damage_mult(skill.element, _weather_key(state.weather_type))

    atk_marks = state.marks_a if attacker in state.team_a else state.marks_b
    mark_buff = apply_marks_to_attack_power(skill.power, skill.element, atk_marks, attacker.elements[0])
    counter_buff = COUNTER_DAMAGE_BONUS if countered else 1.0
    env_mod = attacker._power_mod
    power_buff = mark_buff * counter_buff * (attacker.power_mult / 100.0) * env_mod

    damage = calc_attack_damage(skill.power, atk, dfn, type_mult,
        stab=stab, weather=weather_mult, hit_count=skill.hit_count, power_buff=power_buff)

    dfn_marks = state.marks_b if defender in state.team_b else state.marks_a
    if skill.element != "幻":
        meteor = calc_meteor_extra_damage(dfn_marks)
        if meteor > 0: damage += meteor

    reduction = defender._defense_reduction
    if reduction > 0:
        damage = max(1, int(damage * (1.0 - reduction)))
        defender._defense_reduction = 0.0

    defender.current_hp = max(0, defender.current_hp - damage)
    attacker._power_mod = 1.0

    state.log.append(BattleEvent(
        turn=state.turn_number, actor=attacker.persistent.name, action="attack",
        detail={"move": skill.name, "damage": damage, "target": defender.persistent.name,
                "type_mult": type_mult, "stab": stab, "countered": countered,
                "target_hp_pct": round(defender.hp_pct * 100, 1)}))

    _emit(bus, "ON_DAMAGE", state, attacker, defender,
          {"skill": skill, "damage": damage, "countered": countered})
    _emit(bus, "TAKE_DAMAGE", state, defender, attacker,
          {"skill": skill, "damage": damage, "countered": countered})
    return damage


def register_skill_handlers(bus):
    set_bus(bus)
    import importlib
    for mod_name in [
        "roco.systems.skill_pre_use", "roco.systems.skill_on_damage",
        "roco.systems.skill_post_use", "roco.systems.skill_leech",
        "roco.systems.skill_counter",
    ]:
        importlib.import_module(mod_name).register(bus)
