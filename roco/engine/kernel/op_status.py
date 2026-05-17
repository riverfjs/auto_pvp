"""Status and weather effect primitives."""

from __future__ import annotations

from roco.engine.kernel.ctx import StageCtx
from roco.engine.kernel.op_rows import ROW_ARG0, ROW_ARG1


def op_burn(ctx: StageCtx, row: tuple[int, ...]) -> None:
    ctx.burn_stacks += row[ROW_ARG0]


def op_poison(ctx: StageCtx, row: tuple[int, ...]) -> None:
    ctx.poison_stacks += row[ROW_ARG0]


def op_freeze(ctx: StageCtx, row: tuple[int, ...]) -> None:
    ctx.freeze_stacks += row[ROW_ARG0]


def op_leech(ctx: StageCtx, row: tuple[int, ...]) -> None:
    ctx.leech_stacks += row[ROW_ARG0]


def op_weather(ctx: StageCtx, row: tuple[int, ...]) -> None:
    ctx.weather = row[ROW_ARG0]
    ctx.weather_turns = row[ROW_ARG1]


def op_on_skill_element_poison(ctx: StageCtx, row: tuple[int, ...]) -> None:
    if ctx.skill_element == row[ROW_ARG0]:
        ctx.poison_stacks += row[ROW_ARG1]


def op_on_skill_element_burn(ctx: StageCtx, row: tuple[int, ...]) -> None:
    if ctx.skill_element == row[ROW_ARG0]:
        ctx.burn_stacks += row[ROW_ARG1]


def op_on_skill_element_freeze(ctx: StageCtx, row: tuple[int, ...]) -> None:
    if ctx.skill_element == row[ROW_ARG0]:
        ctx.freeze_stacks += row[ROW_ARG1]


def op_poison_on_skill_apply(ctx: StageCtx, row: tuple[int, ...]) -> None:
    if ctx.skill_energy <= row[ROW_ARG0]:
        ctx.poison_stacks += row[ROW_ARG1]
