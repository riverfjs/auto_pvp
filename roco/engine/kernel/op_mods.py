"""Damage, modifier, switch, and lifecycle effect primitives."""

from __future__ import annotations

from roco.engine.common.packing import BUFF_ATK_MAG, BUFF_ATK_PHYS, BUFF_DEF_MAG, BUFF_DEF_PHYS, BUFF_SPEED, _add_buff_bps, _unpack_skill_count
from roco.engine.common.rules import BLOODLINE_LEADER, BLOODLINE_POLLUTANT, BPS
from roco.engine.enums import Element
from roco.engine.kernel.catalog import ELEMENT_LIGHT, SKILL_FLAG_CHARGE
from roco.engine.kernel.ctx import StageCtx
from roco.engine.kernel.op_rows import (
    ROW_ARG0,
    ROW_ARG1,
    ROW_ARG2,
    ROW_ARG3,
    ROW_TAG,
    ROW_TARGET,
    TARGET_ALLY,
    TARGET_SELF,
    TARGET_TEAM,
)


def op_damage(ctx: StageCtx, row: tuple[int, ...]) -> None:
    if row[ROW_ARG0] > 0:
        ctx.power = row[ROW_ARG0]
    if row[ROW_ARG1] > 0:
        ctx.hit_count = row[ROW_ARG1]


def op_damage_reduction(ctx: StageCtx, row: tuple[int, ...]) -> None:
    if row[ROW_ARG0] > 0:
        ctx.damage_reduction_bps = min(ctx.damage_reduction_bps, row[ROW_ARG0])


def op_self_buff(ctx: StageCtx, row: tuple[int, ...]) -> None:
    ctx.self_buff |= row[ROW_ARG0]


def op_self_debuff(ctx: StageCtx, row: tuple[int, ...]) -> None:
    ctx.self_buff |= row[ROW_ARG0]


def op_enemy_debuff(ctx: StageCtx, row: tuple[int, ...]) -> None:
    ctx.enemy_buff |= row[ROW_ARG0]


def op_force_switch(ctx: StageCtx, row: tuple[int, ...]) -> None:
    ctx.force_switch = 1


def op_force_enemy_switch(ctx: StageCtx, row: tuple[int, ...]) -> None:
    ctx.force_enemy_switch = 1


def op_counter_attack(ctx: StageCtx, row: tuple[int, ...]) -> None:
    ctx.counter_damage += row[ROW_ARG0]


def op_auto_switch_on_zero_energy(ctx: StageCtx, row: tuple[int, ...]) -> None:
    if ctx.actor_energy <= 0:
        ctx.force_switch = 1


def op_cleanse(ctx: StageCtx, row: tuple[int, ...]) -> None:
    if row[ROW_TARGET] in (TARGET_SELF, TARGET_ALLY, TARGET_TEAM):
        ctx.cleanse_self = 1
        ctx.clear_self_buffs = 1
        ctx.clear_self_debuffs = 1
    else:
        ctx.cleanse_enemy = 1
        ctx.clear_enemy_buffs = 1
        ctx.clear_enemy_debuffs = 1


def op_dispel_buffs(ctx: StageCtx, row: tuple[int, ...]) -> None:
    if row[ROW_TARGET] in (TARGET_SELF, TARGET_ALLY, TARGET_TEAM):
        ctx.clear_self_buffs = 1
    else:
        ctx.clear_enemy_buffs = 1


def op_dispel_debuffs(ctx: StageCtx, row: tuple[int, ...]) -> None:
    if row[ROW_TARGET] in (TARGET_SELF, TARGET_ALLY, TARGET_TEAM):
        ctx.clear_self_debuffs = 1
    else:
        ctx.clear_enemy_debuffs = 1


def op_power_dynamic(ctx: StageCtx, row: tuple[int, ...]) -> None:
    if row[ROW_ARG0] > 0:
        ctx.power_bps = (ctx.power_bps * row[ROW_ARG0]) // BPS
    if row[ROW_ARG1] > 0:
        ctx.power += row[ROW_ARG1]


def op_permanent_mod(ctx: StageCtx, row: tuple[int, ...]) -> None:
    if row[ROW_ARG0] == 2:
        ctx.power += row[ROW_ARG1]
    elif row[ROW_ARG0] == 3:
        ctx.hit_count += row[ROW_ARG1]


def op_next_attack_mod(ctx: StageCtx, row: tuple[int, ...]) -> None:
    ctx.power += row[ROW_ARG0]


def op_interrupt(ctx: StageCtx, row: tuple[int, ...]) -> None:
    ctx.interrupt = 1


def op_skill_mod(ctx: StageCtx, row: tuple[int, ...]) -> None:
    if ctx.skill_slot < 0 or not (row[ROW_ARG0] & (1 << ctx.skill_slot)):
        return
    ctx.power += row[ROW_ARG2]
    ctx.hit_count += row[ROW_ARG3]


def op_specific_skill_power_bonus(ctx: StageCtx, row: tuple[int, ...]) -> None:
    if ctx.skill_id == row[ROW_ARG0]:
        ctx.power += row[ROW_ARG1]


def op_power_by_status_count_elements(ctx: StageCtx, row: tuple[int, ...]) -> None:
    if row[ROW_ARG0] & (1 << ctx.skill_element):
        ctx.power += ctx.side_status_skill_count * row[ROW_ARG1]


def op_counter_success_speed_priority(ctx: StageCtx, row: tuple[int, ...]) -> None:
    if ctx.counter_success:
        ctx.priority_next += row[ROW_ARG0]


def op_transfer_mods(ctx: StageCtx, row: tuple[int, ...]) -> None:
    ctx.swap_mods = 1


def op_exchange_moves(ctx: StageCtx, row: tuple[int, ...]) -> None:
    ctx.swap_moves = 1


def op_exchange_hp_ratio(ctx: StageCtx, row: tuple[int, ...]) -> None:
    ctx.exchange_hp_ratio = 1


def op_borrow_team_skill(ctx: StageCtx, row: tuple[int, ...]) -> None:
    ctx.cancelled = 0


def op_on_interrupt_cooldown(ctx: StageCtx, row: tuple[int, ...]) -> None:
    if ctx.interrupt:
        ctx.enemy_cooldown_turns = max(ctx.enemy_cooldown_turns, row[ROW_ARG0])


def op_charge_cost_reduce(ctx: StageCtx, row: tuple[int, ...]) -> None:
    if ctx.skill_flags & SKILL_FLAG_CHARGE:
        ctx.cost_delta -= row[ROW_ARG0]


def op_energy_drain_by_cost_diff(ctx: StageCtx, row: tuple[int, ...]) -> None:
    diff = ctx.skill_energy - ctx.target_skill_energy
    if diff > 0:
        ctx.enemy_lose_energy += diff


def op_counter_accumulate_transform(ctx: StageCtx, row: tuple[int, ...]) -> None:
    if not ctx.counter_success:
        return
    required_category = row[ROW_ARG1]
    if required_category and ctx.counter_category != required_category:
        return
    if ctx.actor_counter_count >= row[ROW_ARG0]:
        ctx.form_transform = 1
        ctx.form_transform_heal = row[ROW_ARG2]


def op_hit_count_delta(ctx: StageCtx, row: tuple[int, ...]) -> None:
    if row[ROW_TARGET] == TARGET_SELF:
        ctx.hit_count += row[ROW_ARG0]
    else:
        ctx.enemy_hit_delta += row[ROW_ARG0]


def op_debuff_extra_layers(ctx: StageCtx, row: tuple[int, ...]) -> None:
    ctx.debuff_extra_layers += row[ROW_ARG0]


def op_damage_mod_non_stab(ctx: StageCtx, row: tuple[int, ...]) -> None:
    if ctx.skill_element not in (ctx.actor_primary, ctx.actor_secondary):
        ctx.power_bps = ctx.power_bps * row[ROW_ARG0] // BPS


def op_damage_mod_non_light(ctx: StageCtx, row: tuple[int, ...]) -> None:
    if ctx.skill_element != ELEMENT_LIGHT:
        ctx.power_bps = ctx.power_bps * row[ROW_ARG0] // BPS


def op_damage_mod_non_weakness(ctx: StageCtx, row: tuple[int, ...]) -> None:
    from roco.engine.generated import catalog_hot as hot
    first = hot.TYPE_CHART_BPS[ctx.skill_element][ctx.target_primary]
    second = BPS if ctx.target_secondary < 0 else hot.TYPE_CHART_BPS[ctx.skill_element][ctx.target_secondary]
    if not (first > BPS or second > BPS):
        ctx.power_bps = ctx.power_bps * row[ROW_ARG0] // BPS


def op_damage_mod_leader_blood(ctx: StageCtx, row: tuple[int, ...]) -> None:
    if ctx.target_bloodline == BLOODLINE_LEADER:
        ctx.power_bps = ctx.power_bps * row[ROW_ARG0] // BPS


def op_damage_mod_pollutant(ctx: StageCtx, row: tuple[int, ...]) -> None:
    if ctx.target_bloodline == BLOODLINE_POLLUTANT:
        ctx.power_bps = ctx.power_bps * row[ROW_ARG0] // BPS


def op_on_skill_element_buff(ctx: StageCtx, row: tuple[int, ...]) -> None:
    if ctx.skill_element == row[ROW_ARG0]:
        ctx.self_buff |= row[ROW_ARG1]


def op_carry_skill_power_bonus(ctx: StageCtx, row: tuple[int, ...]) -> None:
    condition = row[ROW_ARG0]
    value = row[ROW_ARG1]
    applies = (
        condition == 0
        or (condition == 1 and ctx.skill_energy == value)
        or (condition == 2 and ctx.skill_energy > value)
        or (condition == 3 and ctx.skill_energy <= value)
    )
    if applies:
        ctx.power_bps = ctx.power_bps * row[ROW_ARG2] // BPS


def op_bloodline_entry(ctx: StageCtx, row: tuple[int, ...]) -> None:
    if ctx.actor_bloodline == row[ROW_ARG0]:
        ctx.enemy_buff |= row[ROW_ARG1]


def op_first_strike_hit_count(ctx: StageCtx, row: tuple[int, ...]) -> None:
    if ctx.first_strike:
        ctx.hit_count += row[ROW_ARG0]


def op_hit_count_per_poison(ctx: StageCtx, row: tuple[int, ...]) -> None:
    ctx.hit_count += ctx.target_poison_stacks * row[ROW_ARG0]


def op_stat_scale_hits_per_hp_lost(ctx: StageCtx, row: tuple[int, ...]) -> None:
    ctx.hit_count += ctx.actor_hp_lost_quarters * row[ROW_ARG0]


def op_on_skill_element_hit_count(ctx: StageCtx, row: tuple[int, ...]) -> None:
    if ctx.skill_element == row[ROW_ARG0]:
        ctx.hit_count += row[ROW_ARG1]


def op_entry_buff_per_skill_count(ctx: StageCtx, row: tuple[int, ...]) -> None:
    count = _unpack_skill_count(ctx.side_skill_counts, Element(row[ROW_ARG0]))
    if row[ROW_ARG1] == 1:
        ctx.entry_cost_delta -= count * row[ROW_ARG2]
    elif row[ROW_ARG1] == 2:
        ctx.entry_power_bonus += count * row[ROW_ARG2]


def op_team_synergy_bug_swarm_attack(ctx: StageCtx, row: tuple[int, ...]) -> None:
    bonus = ctx.side_bug_count * row[ROW_ARG0]
    if bonus <= 0:
        return
    packed = 0
    for idx in (BUFF_ATK_PHYS, BUFF_ATK_MAG, BUFF_DEF_PHYS, BUFF_DEF_MAG, BUFF_SPEED):
        packed = _add_buff_bps(packed, idx, bonus)
    ctx.self_buff |= packed


def op_on_super_effective_buff(ctx: StageCtx, row: tuple[int, ...]) -> None:
    if ctx.super_effective:
        ctx.self_buff |= row[ROW_ARG0]
        ctx.heal_energy += row[ROW_ARG1]


def op_devotion_grant_random(ctx: StageCtx, row: tuple[int, ...]) -> None:
    ctx.devotion_random += row[ROW_ARG0]


def op_mirror_enemy_buffs(ctx: StageCtx, row: tuple[int, ...]) -> None:
    ctx.mirror_enemy_buffs = 1


def op_contract_entry(ctx: StageCtx, row: tuple[int, ...]) -> None:
    ctx.self_buff |= row[ROW_ARG0]
    ctx.poison_stacks += row[ROW_ARG1]
