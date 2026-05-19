"""Damage-amount primitives: base damage, reductions, and damage-mod ops."""

from __future__ import annotations

from roco.common.constants import BLOODLINE_LEADER, BLOODLINE_POLLUTANT, BPS
from roco.engine.kernel.catalog import ELEMENT_LIGHT
from roco.engine.kernel.ctx import StageCtx
from roco.engine.kernel.op_rows import ROW_ARG0, ROW_ARG1


def op_damage(ctx: StageCtx, row: tuple[int, ...]) -> None:
    if row[ROW_ARG0] > 0:
        ctx.power = row[ROW_ARG0]
    if row[ROW_ARG1] > 0:
        ctx.hit_count = row[ROW_ARG1]


def op_damage_reduction(ctx: StageCtx, row: tuple[int, ...]) -> None:
    if row[ROW_ARG0] > 0:
        ctx.damage_reduction_bps = min(ctx.damage_reduction_bps, row[ROW_ARG0])


def op_damage_mod_non_stab(ctx: StageCtx, row: tuple[int, ...]) -> None:
    if ctx.skill_element not in (ctx.actor_primary, ctx.actor_secondary):
        ctx.power_bps = ctx.power_bps * row[ROW_ARG0] // BPS


def op_damage_mod_non_light(ctx: StageCtx, row: tuple[int, ...]) -> None:
    if ctx.skill_element != ELEMENT_LIGHT:
        ctx.power_bps = ctx.power_bps * row[ROW_ARG0] // BPS


def op_damage_mod_non_weakness(ctx: StageCtx, row: tuple[int, ...]) -> None:
    # Lazy import — catalog_hot may not exist during the first codegen pass.
    from roco.generated import catalog_hot as hot

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
