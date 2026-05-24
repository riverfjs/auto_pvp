"""Skill-level mods: power/hit_count tuning, swapping, and per-skill conditions."""

from __future__ import annotations

from roco.common.constants import BPS
from roco.common.enums import Element
from roco.common.packing import _add_element_nibble, _add_element_u8
from roco.common.skill_mod_modes import (
    ENTRY_MOD_COST_REDUCE,
    ENTRY_MOD_POISON_STACKS,
    ENTRY_MOD_POWER_BPS,
    ENTRY_MOD_POWER_FLAT,
)
from roco.engine.kernel.conditions import entry_source_count, slot_mask_matches
from roco.engine.kernel.ctx import StageCtx
from roco.engine.kernel.op_meta import handles_buff
from roco.engine.kernel.op_rows import (
    ROW_ARG0,
    ROW_ARG1,
    ROW_ARG2,
    ROW_ARG3,
    ROW_TIMING,
    TIMING_BEFORE_MOVE,
)

@handles_buff([
    ("BFT_INC_DAM_BY_ATTACK_FIRST", "PRIORITY"),
    ("BFT_INC_DAM_BY_SKILL", "POWER_MOD"),
    ("BFT_BLOOD_TO_ENERGY", "EARTH_HEART"),
    ("BFT_NOT_GET_HIT", "MOMENTUM"),
    ("BFT_INC_DAM_BY_TARGET_HP_THRES", "FIRE_RAGE"),
    ("BFT_CHANGE_GAIN_ENERGY_EFFECIENCY", "OVERLOAD"),
    ("BFT_O_SEVEN", "COND_POWER"),
    ("BFT_O_EIGHT", "FLAT_POWER"),
])
def op_power_dynamic(ctx: StageCtx, row: tuple[int, ...]) -> None:
    if row[ROW_ARG0] > 0:
        ctx.power_bps = (ctx.power_bps * row[ROW_ARG0]) // BPS
    if row[ROW_ARG1] > 0:
        ctx.power += row[ROW_ARG1]


def op_skill_mod(ctx: StageCtx, row: tuple[int, ...]) -> None:
    if not slot_mask_matches(ctx, row[ROW_ARG0]):
        return
    if row[ROW_TIMING] == TIMING_BEFORE_MOVE:
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


def op_entry_element_skill_mod_by_count(ctx: StageCtx, row: tuple[int, ...]) -> None:
    count = entry_source_count(ctx, row[ROW_ARG0])
    if count <= 0:
        return
    amount = row[ROW_ARG2] * count
    mode = row[ROW_ARG3]
    for element in Element:
        if not (row[ROW_ARG1] & (1 << element.value)):
            continue
        if mode == ENTRY_MOD_POWER_BPS:
            ctx.entry_element_power_bps = _add_element_u8(
                ctx.entry_element_power_bps,
                element,
                amount // 100,
            )
        elif mode == ENTRY_MOD_POWER_FLAT:
            ctx.entry_element_power_flat = _add_element_u8(
                ctx.entry_element_power_flat,
                element,
                amount,
            )
        elif mode == ENTRY_MOD_COST_REDUCE:
            ctx.entry_element_cost_reduce = _add_element_nibble(
                ctx.entry_element_cost_reduce,
                element,
                amount,
            )
        elif mode == ENTRY_MOD_POISON_STACKS:
            ctx.entry_element_poison_stacks = _add_element_nibble(
                ctx.entry_element_poison_stacks,
                element,
                amount,
            )


def op_transfer_mods(ctx: StageCtx, row: tuple[int, ...]) -> None:
    ctx.swap_mods = 1


def op_exchange_moves(ctx: StageCtx, row: tuple[int, ...]) -> None:
    ctx.swap_moves = 1


def op_exchange_hp_ratio(ctx: StageCtx, row: tuple[int, ...]) -> None:
    ctx.exchange_hp_ratio = 1


def op_borrow_team_skill(ctx: StageCtx, row: tuple[int, ...]) -> None:
    ctx.cancelled = 0
