"""Counter-skill execution helpers."""

from __future__ import annotations

from roco.common.enums import SkillCategory
from roco.engine.kernel.core.ctx import StageCtx
from roco.engine.kernel.effects.damage import damage
from roco.engine.kernel.model.state import KernelState, replace_pet, replace_side, side
from roco.engine.kernel.flow.switch import faint_pet
from roco.generated.pak.counter_skill_table import COUNTER_SKILL_TABLE


def fire_counter_skill(
    state: KernelState,
    attacker_side_id: int,
    attacker_slot: int,
    defender_side_id: int,
    defender_slot: int,
    first_strike: bool,
) -> tuple[KernelState, int]:
    defender_side = side(state, defender_side_id)
    counter_skill_id = defender_side.counter_skill_id
    if counter_skill_id == 0:
        return state, 0
    defender_side = defender_side._replace(counter_skill_id=0)
    state = replace_side(state, defender_side_id, defender_side)
    stats = COUNTER_SKILL_TABLE.get(counter_skill_id)
    if stats is None:
        return state, 0
    power, element, category, _dam_type, _priority = stats
    if power <= 0 or category not in (SkillCategory.PHYSICAL.value, SkillCategory.MAGICAL.value):
        return state, 0
    attacker_side = side(state, attacker_side_id)
    attacker = attacker_side.pets[attacker_slot]
    defender = defender_side.pets[defender_slot]
    if attacker.fainted or defender.fainted:
        return state, 0
    counter_ctx = StageCtx()
    counter_ctx.reset(defender_side_id, defender_slot, attacker_side_id, attacker_slot, counter_skill_id)
    counter_ctx.skill_element = element
    counter_ctx.skill_category = category
    counter_ctx.power = power
    counter_ctx.hit_count = 1
    counter_skill = (counter_skill_id, element, category, 0, power, 0, 1, 0)
    dealt = damage(
        defender,
        attacker,
        counter_skill,
        counter_ctx,
        state.weather,
        defender_side.marks,
        attacker_side.marks,
        first_strike,
    )
    if dealt <= 0:
        return state, 0
    attacker = attacker._replace(current_hp=max(0, attacker.current_hp - dealt))
    attacker_side = replace_pet(attacker_side, attacker_slot, attacker)
    state = replace_side(state, attacker_side_id, attacker_side)
    if attacker.current_hp <= 0:
        state = faint_pet(state, attacker_side_id, attacker_slot, defender_side_id, defender_slot)
    return state, dealt
