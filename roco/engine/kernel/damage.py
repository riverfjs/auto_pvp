"""Integer damage and mark/type modifiers for the fixed kernel."""

from __future__ import annotations

from roco.common.packing import (
    BUFF_ATK_MAG,
    BUFF_ATK_PHYS,
    BUFF_DEF_MAG,
    BUFF_DEF_PHYS,
    MarkIdx,
    _unpack_element_u8,
    _unpack_mark,
    _unpack_status,
    stat_ratio_bps,
)
from roco.common.constants import (
    BPS,
    BURN_DAMAGE_BPS,
    BURN_HP_CAP,
    CUTE_DAMAGE_BPS_PER_STACK,
    DAMAGE_CONST_BPS,
    LEECH_DAMAGE_BPS,
    MARK_ATTACK_BPS,
    MARK_DRAGON_BPS,
    MARK_MOMENTUM_BPS,
    MARK_SLUGGISH_BPS,
    MARK_WIND_BPS,
    METEOR_POWER,
    MIN_DAMAGE,
    MOISTURE_COST_REDUCE,
    MOMENTUM_COST_UP,
    POISON_DAMAGE_BPS,
    RAIN_WATER_BPS,
    SLOW_SPEED_REDUCE,
    STAB_BPS,
    TYPE_DOUBLE_RESIST_BPS,
    TYPE_DOUBLE_WEAK_BPS,
    TYPE_NEUTRAL_BPS,
    TYPE_RESIST_BPS,
)
from roco.common.enums import AbilityFlag, Element, SkillCategory, StatusFlag, StatusType, WeatherType
from roco.generated import catalog_hot as hot
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
from roco.engine.kernel.ctx import StageCtx
from roco.engine.kernel.state import PetState, weather_type


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
    if target.ability_flags & int(AbilityFlag.IMMUNE_ZERO_ENERGY_ATTACKER) and actor.current_energy <= 0:
        return 0
    if target.ability_flags & int(AbilityFlag.IMMUNE_LOW_COST_ATTACK) and skill[SKILL_ENERGY] <= 1:
        return 0
    if ctx.power <= 0 or atk <= 0 or defense <= 1:
        return 0
    power = max(0, (ctx.power * ctx.power_bps) // BPS)
    stat_bps = stat_ratio_bps(
        actor.buff_stages,
        BUFF_ATK_PHYS if physical else BUFF_ATK_MAG,
        target.buff_stages,
        BUFF_DEF_PHYS if physical else BUFF_DEF_MAG,
    )
    type_bps_value = BPS if actor.ability_flags & int(AbilityFlag.BARREL_ACTIVE) else type_bps(
        skill[SKILL_ELEMENT], target_row[PET_PRIMARY], target_row[PET_SECONDARY]
    )
    ctx.super_effective = 1 if type_bps_value > BPS else 0
    stab_bps = STAB_BPS if skill[SKILL_ELEMENT] in (actor_row[PET_PRIMARY], actor_row[PET_SECONDARY]) else BPS
    weather_bps = weather_damage_bps(skill[SKILL_ELEMENT], weather)
    mark_bps = mark_attack_bps(actor_marks, first_strike, skill[SKILL_ENERGY])
    cute_bps = BPS + actor.cute * CUTE_DAMAGE_BPS_PER_STACK
    element_reduce_pct = min(
        100,
        _unpack_element_u8(target.element_damage_reduce, Element(skill[SKILL_ELEMENT])),
    )
    if element_reduce_pct:
        ctx.damage_reduction_bps = min(ctx.damage_reduction_bps, max(0, BPS - element_reduce_pct * 100))
    if target.element_damage_resist & (1 << skill[SKILL_ELEMENT]):
        ctx.damage_reduction_bps = min(ctx.damage_reduction_bps, TYPE_RESIST_BPS)
    total = (
        atk
        * stat_bps
        * power
        * DAMAGE_CONST_BPS
        * type_bps_value
        * stab_bps
        * weather_bps
        * mark_bps
        * cute_bps
        * _hit_count(actor, target, ctx)
    ) // (defense * (BPS ** 7))
    total = max(MIN_DAMAGE, total)
    if skill[SKILL_ELEMENT] != ELEMENT_ILLUSION:
        total += _meteor_damage_stacks(actor, target, target_marks) * METEOR_POWER
    total += ctx.flat_damage
    return max(0, (total * ctx.damage_bps * ctx.damage_reduction_bps) // (BPS * BPS))


def _hit_count(actor: PetState, target: PetState, ctx: StageCtx) -> int:
    if (actor.ability_flags | target.ability_flags) & int(AbilityFlag.FIXED_HIT_COUNT_ALL):
        return 2
    return max(1, ctx.hit_count)


def _meteor_damage_stacks(actor: PetState, target: PetState, target_marks: int) -> int:
    stacks = _unpack_mark(target_marks, MarkIdx.METEOR)
    if actor.ability_flags & int(AbilityFlag.FREEZE_COUNTS_AS_METEOR):
        stacks += _unpack_status(target.status_counts, StatusType.FREEZE)
    return stacks


def weather_damage_bps(skill_element: int, weather: int) -> int:
    if weather_type(weather) == WeatherType.RAIN.value and skill_element == ELEMENT_WATER:
        return RAIN_WATER_BPS
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
    bonus += _unpack_mark(marks, MarkIdx.ATTACK) * MARK_ATTACK_BPS
    bonus += _unpack_mark(marks, MarkIdx.MOMENTUM) * MARK_MOMENTUM_BPS
    if first_strike:
        bonus += _unpack_mark(marks, MarkIdx.WIND) * MARK_WIND_BPS
    else:
        bonus += _unpack_mark(marks, MarkIdx.SLUGGISH) * MARK_SLUGGISH_BPS
    if base_energy == 5:
        bonus += _unpack_mark(marks, MarkIdx.DRAGON) * MARK_DRAGON_BPS
    return BPS + bonus


def type_bps(move_element: int, primary: int, secondary: int) -> int:
    first = hot.TYPE_CHART_BPS[move_element][primary]
    if secondary < 0:
        return first
    second = hot.TYPE_CHART_BPS[move_element][secondary]
    if first > BPS and second > BPS:
        return TYPE_DOUBLE_WEAK_BPS
    if first < BPS and second < BPS:
        return TYPE_DOUBLE_RESIST_BPS
    if (first > BPS and second < BPS) or (first < BPS and second > BPS):
        return TYPE_NEUTRAL_BPS
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
