"""Skill-level mods: power/hit_count tuning, swapping, and per-skill conditions."""

from __future__ import annotations

from roco.common.constants import BPS
from roco.common.enums import Element, SkillCategory
from roco.common.packing import _add_element_nibble, _add_element_u8, _max_element_u8
from roco.generated.pak.bloodline_magic import PAK_BLOODLINE_LEADER, PAK_BLOODLINE_POLLUTANT, PAK_ELEMENT_TO_BLOODLINE
from roco.engine.kernel.effects.conditions import entry_source_count, slot_mask_matches
from roco.engine.kernel.core.ctx import StageCtx
from roco.engine.kernel.core.rows import (
    ROW_ARG0,
    ROW_ARG1,
    ROW_ARG2,
    ROW_ARG3,
    ROW_TARGET,
    ROW_TIMING,
    TARGET_ALLY,
    TARGET_SELF,
    TARGET_TEAM,
    TIMING_HOOK_BEFORE_MOVE,
)

def op_power_dynamic(ctx: StageCtx, row: tuple[int, ...]) -> None:
    if row[ROW_ARG0] > 0:
        ctx.power_bps = (ctx.power_bps * row[ROW_ARG0]) // BPS
    if row[ROW_ARG1] != 0:
        ctx.power += row[ROW_ARG1]


def op_power_dynamic_elements(ctx: StageCtx, row: tuple[int, ...]) -> None:
    if not row[ROW_ARG0] & (1 << ctx.skill_element):
        return
    if row[ROW_ARG1] > 0:
        ctx.power_bps = (ctx.power_bps * row[ROW_ARG1]) // BPS
    if row[ROW_ARG2] != 0:
        ctx.power += row[ROW_ARG2]


def op_power_bps_by_target_meteor_mark(ctx: StageCtx, row: tuple[int, ...]) -> None:
    raw_skill_dam_type = row[ROW_ARG0]
    if raw_skill_dam_type and ctx.skill_dam_type != raw_skill_dam_type:
        return
    count = ctx.target_meteor_mark_stacks
    if count > 0:
        ctx.power_bps = ctx.power_bps * (BPS + count * row[ROW_ARG1]) // BPS


def op_power_bps_by_target_positive_buff_layers(ctx: StageCtx, row: tuple[int, ...]) -> None:
    count = ctx.target_positive_buff_layers
    if count > 0:
        ctx.power_bps = ctx.power_bps * (BPS + count * row[ROW_ARG0]) // BPS


def op_power_flat_by_target_skill_type_count(ctx: StageCtx, row: tuple[int, ...]) -> None:
    if ctx.target_equipped_skill_type_count > 0:
        ctx.power += ctx.target_equipped_skill_type_count * row[ROW_ARG0]


def op_power_bps_by_target_skill_total_cost(ctx: StageCtx, row: tuple[int, ...]) -> None:
    if ctx.target_equipped_skill_total_cost > 0:
        ctx.power_bps = ctx.power_bps * (BPS + ctx.target_equipped_skill_total_cost * row[ROW_ARG0]) // BPS


def op_power_bps_if_target_bloodline(ctx: StageCtx, row: tuple[int, ...]) -> None:
    mode = row[ROW_ARG0]
    applies = (
        (mode == 1 and ctx.target_bloodline == PAK_BLOODLINE_LEADER)
        or (mode == 2 and ctx.target_bloodline == PAK_BLOODLINE_POLLUTANT)
        or (mode == 3 and _target_bloodline_is_non_stab_element(ctx))
    )
    if applies:
        ctx.power_bps = ctx.power_bps * (BPS + row[ROW_ARG1]) // BPS


def _target_bloodline_is_non_stab_element(ctx: StageCtx) -> bool:
    if ctx.target_bloodline <= 0:
        return False
    own = {PAK_ELEMENT_TO_BLOODLINE[ctx.target_primary]}
    if ctx.target_secondary >= 0:
        own.add(PAK_ELEMENT_TO_BLOODLINE[ctx.target_secondary])
    return ctx.target_bloodline in PAK_ELEMENT_TO_BLOODLINE and ctx.target_bloodline not in own


def op_first_strike_power_bps(ctx: StageCtx, row: tuple[int, ...]) -> None:
    if not ctx.first_strike:
        return
    category_scope = row[ROW_ARG0]
    if category_scope == 1 and ctx.skill_category not in (SkillCategory.PHYSICAL.value, SkillCategory.MAGICAL.value):
        return
    ctx.power_bps = (ctx.power_bps * row[ROW_ARG1]) // BPS


def op_skill_mod(ctx: StageCtx, row: tuple[int, ...]) -> None:
    if not slot_mask_matches(ctx, row[ROW_ARG0]):
        return
    if row[ROW_TIMING] == TIMING_HOOK_BEFORE_MOVE:
        ctx.cost_delta -= row[ROW_ARG1]
    ctx.power += row[ROW_ARG2]
    ctx.hit_count += row[ROW_ARG3]


def op_specific_skill_power_bonus(ctx: StageCtx, row: tuple[int, ...]) -> None:
    if ctx.skill_id == row[ROW_ARG0]:
        ctx.power += row[ROW_ARG1]


def op_power_by_status_count_elements(ctx: StageCtx, row: tuple[int, ...]) -> None:
    if row[ROW_ARG0] & (1 << ctx.skill_element):
        ctx.power += ctx.side_status_skill_count * row[ROW_ARG1]


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


def _entry_element_amounts(ctx: StageCtx, row: tuple[int, ...]):
    count = entry_source_count(ctx, row[ROW_ARG0])
    if count <= 0:
        return
    amount = row[ROW_ARG2] * count
    for element in Element:
        if not (row[ROW_ARG1] & (1 << element.value)):
            continue
        yield element, amount


def op_entry_element_power_bps_by_count(ctx: StageCtx, row: tuple[int, ...]) -> None:
    for element, amount in _entry_element_amounts(ctx, row) or ():
        ctx.entry_element_power_bps = _add_element_u8(
            ctx.entry_element_power_bps,
            element,
            amount // 100,
        )


def op_entry_element_power_flat_by_count(ctx: StageCtx, row: tuple[int, ...]) -> None:
    for element, amount in _entry_element_amounts(ctx, row) or ():
        ctx.entry_element_power_flat = _add_element_u8(
            ctx.entry_element_power_flat,
            element,
            amount,
        )


def op_entry_element_cost_reduce_by_count(ctx: StageCtx, row: tuple[int, ...]) -> None:
    for element, amount in _entry_element_amounts(ctx, row) or ():
        ctx.entry_element_cost_reduce = _add_element_nibble(
            ctx.entry_element_cost_reduce,
            element,
            amount,
        )


def op_entry_element_poison_stacks_by_count(ctx: StageCtx, row: tuple[int, ...]) -> None:
    for element, amount in _entry_element_amounts(ctx, row) or ():
        ctx.entry_element_poison_stacks = _add_element_nibble(
            ctx.entry_element_poison_stacks,
            element,
            amount,
        )


def op_entry_element_damage_reduce_by_count(ctx: StageCtx, row: tuple[int, ...]) -> None:
    for element, amount in _entry_element_amounts(ctx, row) or ():
        ctx.entry_element_damage_reduce = _max_element_u8(
            ctx.entry_element_damage_reduce,
            element,
            min(100, amount),
        )


def op_entry_element_damage_resist_by_count(ctx: StageCtx, row: tuple[int, ...]) -> None:
    for element, _amount in _entry_element_amounts(ctx, row) or ():
        ctx.entry_element_damage_resist |= 1 << element.value


def op_clear_element_damage_reduce(ctx: StageCtx, row: tuple[int, ...]) -> None:
    mask = row[ROW_ARG0]
    if row[ROW_TARGET] in (TARGET_SELF, TARGET_ALLY, TARGET_TEAM):
        ctx.clear_self_element_damage_reduce |= mask
    else:
        ctx.clear_enemy_element_damage_reduce |= mask


def op_transfer_mods(ctx: StageCtx, row: tuple[int, ...]) -> None:
    ctx.swap_mods = 1


def op_exchange_moves(ctx: StageCtx, row: tuple[int, ...]) -> None:
    ctx.swap_moves = 1


def op_exchange_hp_ratio(ctx: StageCtx, row: tuple[int, ...]) -> None:
    ctx.exchange_hp_ratio = 1


def op_borrow_team_skill(ctx: StageCtx, row: tuple[int, ...]) -> None:
    ctx.cancelled = 0
