"""Phase-based skill execution — works with ActivePokemon and packed bitfields."""

from __future__ import annotations

from roco.engine.damage import (
    calc_attack_damage, get_type_multiplier, get_stab,
    energy_after_use, can_use_skill,
)
from roco.engine.state import (
    ActivePokemon, SkillData, SkillCategory, BattleEvent, BattleState,
    EffectFlag, StatusFlag, StatusType, Stats, WeatherType,
    _unpack_buff, _set_buff, _unpack_status, _set_status, _pack_cooldown, _unpack_cooldown,
)
from roco.config.constants import COUNTER_DAMAGE_BONUS, MAX_ENERGY
from roco.systems.weather import weather_damage_mult
from roco.systems.marks import apply_marks_to_skill_cost, apply_marks_to_attack_power, calc_meteor_extra_damage


def get_skill_category(pet: ActivePokemon, skill_index: int) -> SkillCategory:
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


def execute_move(attacker: ActivePokemon, defender: ActivePokemon,
                 skill_index: int, state: BattleState, countered: bool = False):
    moves = attacker.persistent.moves
    if skill_index < 0 or skill_index >= len(moves): return
    skill = moves[skill_index]

    cds = _unpack_cooldown(attacker.cooldowns)
    if cds.get(skill_index, 0) > 0: return

    marks = state.marks_a if attacker in state.team_a else state.marks_b
    cost = apply_marks_to_skill_cost(skill.energy, marks)
    if not can_use_skill(attacker.current_energy, cost): return

    exec_skill = skill; exec_index = skill_index
    if attacker.charging_skill >= 0:
        ci = attacker.charging_skill; attacker.charging_skill = -1
        if ci < len(moves): exec_skill = moves[ci]; exec_index = ci

    attacker.current_energy = energy_after_use(attacker.current_energy, cost)
    bus = _get_bus()

    ctx = _emit(bus, "PRE_USE", state, attacker, defender,
                {"skill": exec_skill, "countered": countered})
    if ctx.cancelled: return

    if exec_skill.category in (SkillCategory.PHYSICAL, SkillCategory.MAGICAL):
        _calc_and_apply(attacker, defender, exec_skill, state, countered, bus)

    _emit(bus, "POST_USE", state, attacker, defender,
          {"skill": exec_skill, "countered": countered})

    if exec_skill.effect_flags & EffectFlag.COUNTER:
        cds[exec_index] = 2
    attacker.cooldowns = _pack_cooldown(cds)


def _calc_and_apply(attacker: ActivePokemon, defender: ActivePokemon,
                    skill: SkillData, state: BattleState, countered: bool, bus):
    phys = skill.category in (SkillCategory.PHYSICAL, SkillCategory.PHYSICAL)
    phys = skill.category == SkillCategory.PHYSICAL
    atk = float(attacker.atk_phys if phys else attacker.atk_mag)
    dfn = float(defender.def_phys if phys else defender.def_mag)

    type_mult = get_type_multiplier(skill.element, defender.elements)
    stab = get_stab(skill.element, attacker.elements[0])
    weather_mult = weather_damage_mult(skill.element, WeatherType(state.weather & 0xF).name.lower() if state.weather else None)

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


def register_skill_handlers(bus):
    set_bus(bus)
    import importlib
    for mod_name in [
        "roco.systems.skill_pre_use", "roco.systems.skill_on_damage",
        "roco.systems.skill_post_use", "roco.systems.skill_leech",
        "roco.systems.skill_counter",
    ]:
        importlib.import_module(mod_name).register(bus)
