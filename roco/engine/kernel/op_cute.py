"""Cute stack effect primitives."""

from __future__ import annotations

from roco.engine.kernel.ctx import StageCtx
from roco.engine.kernel.op_meta import handles_buff
from roco.engine.kernel.op_rows import ROW_ARG0, ROW_ARG1


@handles_buff(["BFT_O_TWO"])
def op_cute_gain(ctx: StageCtx, row: tuple[int, ...]) -> None:
    ctx.cute_self += row[ROW_ARG0]


def op_cute_enemy_gain(ctx: StageCtx, row: tuple[int, ...]) -> None:
    ctx.cute_enemy += row[ROW_ARG0]


def op_cute_both(ctx: StageCtx, row: tuple[int, ...]) -> None:
    ctx.cute_self += row[ROW_ARG0]
    ctx.cute_enemy += row[ROW_ARG0]


def op_cute_transfer(ctx: StageCtx, row: tuple[int, ...]) -> None:
    ctx.cute_transfer = 1


def op_cute_clear_self(ctx: StageCtx, row: tuple[int, ...]) -> None:
    ctx.cute_self -= 255


def op_cute_if_power_bonus(ctx: StageCtx, row: tuple[int, ...]) -> None:
    ctx.power += row[ROW_ARG0]


def op_cute_on_gain_power_perm(ctx: StageCtx, row: tuple[int, ...]) -> None:
    ctx.cute_self += row[ROW_ARG0]
    ctx.power += row[ROW_ARG1]


def op_cute_on_gain_cost_reduce(ctx: StageCtx, row: tuple[int, ...]) -> None:
    ctx.cute_self += row[ROW_ARG0]
    ctx.heal_energy += row[ROW_ARG1]


def op_cute_on_gain_speed_perm(ctx: StageCtx, row: tuple[int, ...]) -> None:
    ctx.cute_self += row[ROW_ARG0]
    ctx.self_buff |= row[ROW_ARG1]


def op_cute_team_power(ctx: StageCtx, row: tuple[int, ...]) -> None:
    ctx.hit_count += row[ROW_ARG0]


def op_cute_lethal_shield(ctx: StageCtx, row: tuple[int, ...]) -> None:
    ctx.cute_self += row[ROW_ARG0]


def op_cute_hit_per_stack(ctx: StageCtx, row: tuple[int, ...]) -> None:
    ctx.hit_count += ctx.actor_cute * row[ROW_ARG0]


def op_cute_bench_cost_reduce(ctx: StageCtx, row: tuple[int, ...]) -> None:
    ctx.entry_cost_delta -= ctx.side_bench_cute * row[ROW_ARG0]
