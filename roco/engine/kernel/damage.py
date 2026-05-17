"""Integer damage and mark/type modifiers for the fixed kernel."""

from __future__ import annotations

from roco.config.constants import BURN_HP_CAP, MIN_DAMAGE
from roco.engine.common.packing import MarkIdx, _unpack_mark
from roco.engine.enums import AbilityFlag, SkillCategory, StatusFlag, WeatherType
from roco.engine.generated import catalog_hot as hot
from roco.engine.kernel.catalog import (
    ELEMENT_FIRE,
    ELEMENT_GROUND,
    ELEMENT_ICE,
    ELEMENT_ILLUSION,
    ELEMENT_MECHANICAL,
    ELEMENT_POISON,
    ELEMENT_WATER,
    PET_PRIMARY,
    PET_SECONDARY,
    SKILL_CATEGORY,
    SKILL_ELEMENT,
    SKILL_ENERGY,
    SKILL_POWER,
    STAT_ATK_MAG,
    STAT_ATK_PHYS,
    STAT_DEF_MAG,
    STAT_DEF_PHYS,
    STAT_HP,
)
from roco.engine.kernel.ctx import BPS, StageCtx
from roco.engine.kernel.state import PetState, weather_type

STAB_BPS = 15000
DAMAGE_CONST_BPS = 9000
BURN_DAMAGE_BPS = 200
POISON_DAMAGE_BPS = 300
LEECH_DAMAGE_BPS = 800
RAIN_DAMAGE_BPS = 15000
SLOW_SPEED_REDUCE = 10
MOISTURE_COST_REDUCE = 1
MOMENTUM_COST_UP = 1
METEOR_EXTRA_DAMAGE = 30


def damage(
    actor: PetState,
    target: PetState,
    skill: tuple[int, ...],
    ctx: StageCtx,
    weather: int = 0,
    actor_marks: int = 0,
    target_marks: int = 0,
    first_strike: bool = True,
) -> int:
    actor_row = hot.PETS[actor.pet_id]
    target_row = hot.PETS[target.pet_id]
    physical = skill[SKILL_CATEGORY] == SkillCategory.PHYSICAL.value
    atk = actor_row[STAT_ATK_PHYS] if physical else actor_row[STAT_ATK_MAG]
    defense = target_row[STAT_DEF_PHYS] if physical else target_row[STAT_DEF_MAG]
    if ctx.power <= 0 or atk <= 0 or defense <= 1:
        return 0
    power = max(0, (ctx.power * ctx.power_bps) // BPS)
    type_bps_value = BPS if actor.ability_flags & int(AbilityFlag.BARREL_ACTIVE) else type_bps(
        skill[SKILL_ELEMENT], target_row[PET_PRIMARY], target_row[PET_SECONDARY]
    )
    stab_bps = STAB_BPS if skill[SKILL_ELEMENT] == actor_row[PET_PRIMARY] else BPS
    weather_bps = weather_damage_bps(skill[SKILL_ELEMENT], weather)
    mark_bps = mark_attack_bps(actor_marks, first_strike, skill[SKILL_ENERGY])
    cute_bps = BPS + actor.cute * 500
    per_hit = (
        atk
        * power
        * DAMAGE_CONST_BPS
        * type_bps_value
        * stab_bps
        * weather_bps
        * mark_bps
        * cute_bps
    ) // (defense * BPS * BPS * BPS * BPS * BPS * BPS)
    per_hit = max(MIN_DAMAGE, per_hit)
    total = per_hit * max(1, ctx.hit_count)
    if skill[SKILL_ELEMENT] != ELEMENT_ILLUSION:
        total += _unpack_mark(target_marks, MarkIdx.METEOR) * METEOR_EXTRA_DAMAGE
    total += ctx.flat_damage
    return max(0, (total * ctx.damage_bps) // BPS)


def weather_damage_bps(skill_element: int, weather: int) -> int:
    if weather_type(weather) == WeatherType.RAIN.value and skill_element == ELEMENT_WATER:
        return RAIN_DAMAGE_BPS
    return BPS


def marked_speed(speed: int, marks: int) -> int:
    return max(1, speed - _unpack_mark(marks, MarkIdx.SLOW) * SLOW_SPEED_REDUCE)


def marked_skill_cost(cost: int, marks: int, is_attack: bool) -> int:
    cost -= _unpack_mark(marks, MarkIdx.MOISTURE) * MOISTURE_COST_REDUCE
    if is_attack:
        cost += _unpack_mark(marks, MarkIdx.MOMENTUM) * MOMENTUM_COST_UP
    return max(0, cost)


def mark_attack_bps(marks: int, first_strike: bool, base_energy: int) -> int:
    bonus = 0
    bonus += _unpack_mark(marks, MarkIdx.ATTACK) * 1000
    bonus += _unpack_mark(marks, MarkIdx.MOMENTUM) * 3000
    if first_strike:
        bonus += _unpack_mark(marks, MarkIdx.WIND) * 2000
    else:
        bonus += _unpack_mark(marks, MarkIdx.SLUGGISH) * 3000
    if base_energy == 5:
        bonus += _unpack_mark(marks, MarkIdx.DRAGON) * 4000
    return BPS + bonus


def type_bps(move_element: int, primary: int, secondary: int) -> int:
    first = hot.TYPE_CHART_BPS[move_element][primary]
    if secondary < 0:
        return first
    second = hot.TYPE_CHART_BPS[move_element][secondary]
    if first > BPS and second > BPS:
        return 30000
    if first < BPS and second < BPS:
        return 2500
    if (first > BPS and second < BPS) or (first < BPS and second > BPS):
        return BPS
    return first if first != BPS else second


def burn_damage(pet: PetState, stacks: int) -> int:
    if stacks <= 0:
        return 0
    row = hot.PETS[pet.pet_id]
    hp = min(row[STAT_HP], BURN_HP_CAP)
    return hp * stacks * BURN_DAMAGE_BPS * type_bps(ELEMENT_FIRE, row[PET_PRIMARY], row[PET_SECONDARY]) // (BPS * BPS)


def sandstorm_immune(pet: PetState) -> bool:
    row = hot.PETS[pet.pet_id]
    return row[PET_PRIMARY] in (ELEMENT_GROUND, ELEMENT_MECHANICAL) or row[PET_SECONDARY] in (ELEMENT_GROUND, ELEMENT_MECHANICAL)


def status_immune(pet: PetState, flag: StatusFlag) -> bool:
    row = hot.PETS[pet.pet_id]
    primary = row[PET_PRIMARY]
    secondary = row[PET_SECONDARY]
    if flag == StatusFlag.BURN:
        return primary == ELEMENT_FIRE or secondary == ELEMENT_FIRE
    if flag == StatusFlag.POISON:
        return primary == ELEMENT_POISON or secondary == ELEMENT_POISON
    if flag == StatusFlag.FREEZE:
        return primary == ELEMENT_ICE or secondary == ELEMENT_ICE
    return False
