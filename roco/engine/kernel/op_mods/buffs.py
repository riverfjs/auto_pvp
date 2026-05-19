"""Buff/debuff application, cleansing, dispelling, and conditional buffs."""

from __future__ import annotations

from roco.common.enums import Element
from roco.common.packing import (
    BUFF_ATK_MAG,
    BUFF_ATK_PHYS,
    BUFF_DEF_MAG,
    BUFF_DEF_PHYS,
    BUFF_SPEED,
    _add_buff_bps,
    _unpack_skill_count,
)
from roco.engine.kernel.ctx import StageCtx
from roco.engine.kernel.op_rows import (
    ROW_ARG0,
    ROW_ARG1,
    ROW_ARG2,
    ROW_TARGET,
    TARGET_ALLY,
    TARGET_SELF,
    TARGET_TEAM,
)


def op_self_buff(ctx: StageCtx, row: tuple[int, ...]) -> None:
    ctx.self_buff |= row[ROW_ARG0]


def op_self_debuff(ctx: StageCtx, row: tuple[int, ...]) -> None:
    ctx.self_buff |= row[ROW_ARG0]


def op_enemy_debuff(ctx: StageCtx, row: tuple[int, ...]) -> None:
    ctx.enemy_buff |= row[ROW_ARG0]


def op_permanent_mod(ctx: StageCtx, row: tuple[int, ...]) -> None:
    if row[ROW_ARG0] == 2:
        ctx.power += row[ROW_ARG1]
    elif row[ROW_ARG0] == 3:
        ctx.hit_count += row[ROW_ARG1]


def op_next_attack_mod(ctx: StageCtx, row: tuple[int, ...]) -> None:
    ctx.power += row[ROW_ARG0]


def op_debuff_extra_layers(ctx: StageCtx, row: tuple[int, ...]) -> None:
    ctx.debuff_extra_layers += row[ROW_ARG0]


def op_mirror_enemy_buffs(ctx: StageCtx, row: tuple[int, ...]) -> None:
    ctx.mirror_enemy_buffs = 1


def op_on_super_effective_buff(ctx: StageCtx, row: tuple[int, ...]) -> None:
    if ctx.super_effective:
        ctx.self_buff |= row[ROW_ARG0]
        ctx.heal_energy += row[ROW_ARG1]


def op_on_skill_element_buff(ctx: StageCtx, row: tuple[int, ...]) -> None:
    if ctx.skill_element == row[ROW_ARG0]:
        ctx.self_buff |= row[ROW_ARG1]


def op_bloodline_entry(ctx: StageCtx, row: tuple[int, ...]) -> None:
    if ctx.actor_bloodline == row[ROW_ARG0]:
        ctx.enemy_buff |= row[ROW_ARG1]


def op_contract_entry(ctx: StageCtx, row: tuple[int, ...]) -> None:
    ctx.self_buff |= row[ROW_ARG0]
    ctx.poison_stacks += row[ROW_ARG1]


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
