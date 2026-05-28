"""Resource and cost effect primitives."""

from __future__ import annotations

from roco.common.packing import _unpack_skill_count
from roco.common.constants import BPS
from roco.common.enums import Element, SkillCategory
from roco.engine.kernel.core.catalog import ELEMENT_GRASS
from roco.engine.kernel.core.ctx import StageCtx
from roco.engine.kernel.core.rows import (
    ROW_ARG0,
    ROW_ARG1,
    ROW_ARG2,
    ROW_ARG3,
    ROW_TIMING,
    TIMING_HOOK_BEFORE_MOVE,
)
from roco.engine.kernel.model.state import COST_SCOPE_ALL


def op_heal_hp(ctx: StageCtx, row: tuple[int, ...]) -> None:
    ctx.heal_hp_bps += row[ROW_ARG0]


def op_heal_energy(ctx: StageCtx, row: tuple[int, ...]) -> None:
    ctx.heal_energy += row[ROW_ARG0]


def op_heal_energy_by_target_skill_total_cost(ctx: StageCtx, row: tuple[int, ...]) -> None:
    ctx.heal_energy += ctx.target_equipped_skill_total_cost * row[ROW_ARG0] // BPS


def op_steal_energy(ctx: StageCtx, row: tuple[int, ...]) -> None:
    ctx.steal_energy += row[ROW_ARG0]


def op_enemy_lose_energy(ctx: StageCtx, row: tuple[int, ...]) -> None:
    ctx.enemy_lose_energy += row[ROW_ARG0]


def op_life_drain(ctx: StageCtx, row: tuple[int, ...]) -> None:
    ctx.drain_bps += row[ROW_ARG0]


def op_energy_all_in(ctx: StageCtx, row: tuple[int, ...]) -> None:
    ctx.hp_for_energy = 0


def op_hp_for_energy(ctx: StageCtx, row: tuple[int, ...]) -> None:
    ctx.hp_for_energy = row[ROW_ARG0]


def op_energy_regen_per_turn(ctx: StageCtx, row: tuple[int, ...]) -> None:
    ctx.heal_energy += row[ROW_ARG0]


def op_leave_energy_refill(ctx: StageCtx, row: tuple[int, ...]) -> None:
    ctx.heal_energy += row[ROW_ARG0]


def op_leave_heal_ally(ctx: StageCtx, row: tuple[int, ...]) -> None:
    ctx.heal_hp_bps += row[ROW_ARG0]


def op_enemy_switch_self_cost_reduce(ctx: StageCtx, row: tuple[int, ...]) -> None:
    ctx.entry_cost_delta -= row[ROW_ARG0]


def op_steal_all_enemy_energy(ctx: StageCtx, row: tuple[int, ...]) -> None:
    ctx.steal_energy += row[ROW_ARG0]


def op_enemy_energy_cost_up(ctx: StageCtx, row: tuple[int, ...]) -> None:
    trigger = row[ROW_ARG3]
    if trigger == 1 and ctx.freeze_stacks <= 0:
        return
    if trigger == 2 and ctx.skill_category != SkillCategory.STATUS.value:
        return
    if trigger == 3 and ctx.skill_category not in (SkillCategory.PHYSICAL.value, SkillCategory.MAGICAL.value):
        return
    ctx.enemy_cost_delta += row[ROW_ARG0]
    ctx.enemy_cost_turns = max(ctx.enemy_cost_turns, row[ROW_ARG1])
    ctx.enemy_cost_scope = row[ROW_ARG2] or COST_SCOPE_ALL


def op_heal_on_grass_skill(ctx: StageCtx, row: tuple[int, ...]) -> None:
    if ctx.skill_element == ELEMENT_GRASS:
        ctx.heal_hp_bps += row[ROW_ARG0]


def op_on_skill_element_heal_hp(ctx: StageCtx, row: tuple[int, ...]) -> None:
    if ctx.skill_element == row[ROW_ARG0]:
        ctx.heal_hp_bps += row[ROW_ARG1]


def op_skill_cost_reduction_type(ctx: StageCtx, row: tuple[int, ...]) -> None:
    if ctx.skill_category == row[ROW_ARG0]:
        if row[ROW_TIMING] == TIMING_HOOK_BEFORE_MOVE:
            ctx.cost_delta -= row[ROW_ARG1]
        else:
            ctx.heal_energy += row[ROW_ARG1]


def op_passive_energy_reduce(ctx: StageCtx, row: tuple[int, ...]) -> None:
    ctx.cost_delta -= row[ROW_ARG0]


def op_on_skill_element_cost_reduce(ctx: StageCtx, row: tuple[int, ...]) -> None:
    if ctx.skill_element == row[ROW_ARG0]:
        if row[ROW_TIMING] == TIMING_HOOK_BEFORE_MOVE:
            ctx.cost_delta -= row[ROW_ARG1]
        else:
            ctx.heal_energy += row[ROW_ARG1]


def op_on_skill_element_enemy_energy(ctx: StageCtx, row: tuple[int, ...]) -> None:
    if ctx.skill_element == row[ROW_ARG0]:
        ctx.enemy_lose_energy += row[ROW_ARG1]


def op_entry_energy_from_element_count(ctx: StageCtx, row: tuple[int, ...]) -> None:
    ctx.heal_energy += _unpack_skill_count(ctx.side_skill_counts, Element(row[ROW_ARG0])) * row[ROW_ARG1]


def op_entry_energy_from_counter_count(ctx: StageCtx, row: tuple[int, ...]) -> None:
    ctx.heal_energy += ctx.side_counter_count * row[ROW_ARG0]


def op_entry_self_damage(ctx: StageCtx, row: tuple[int, ...]) -> None:
    ctx.entry_self_damage_bps = max(ctx.entry_self_damage_bps, row[ROW_ARG0])


def op_anti_heal(ctx: StageCtx, row: tuple[int, ...]) -> None:
    ctx.enemy_anti_heal = max(ctx.enemy_anti_heal, row[ROW_ARG0])


def op_grant_life_drain(ctx: StageCtx, row: tuple[int, ...]) -> None:
    ctx.drain_bps = max(ctx.drain_bps, row[ROW_ARG0])


def op_low_cost_skill_power_bonus(ctx: StageCtx, row: tuple[int, ...]) -> None:
    if ctx.skill_energy <= row[ROW_ARG0]:
        ctx.power_bps = ctx.power_bps * row[ROW_ARG1] // BPS
