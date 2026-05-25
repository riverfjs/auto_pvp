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
    _merge_buff_delta,
    _unpack_skill_count,
)
from roco.common.buffbase import pack_buff_delta_from_row, scale_buff_delta
from roco.engine.kernel.conditions import entry_source_count
from roco.engine.kernel.ctx import StageCtx
from roco.engine.kernel.op_rows import (
    ROW_ARG0,
    ROW_ARG1,
    ROW_ARG2,
    ROW_ARG3,
    ROW_TARGET,
    TARGET_ALLY,
    TARGET_ENEMY,
    TARGET_SELF,
    TARGET_TEAM,
)

def op_self_buff(ctx: StageCtx, row: tuple[int, ...]) -> None:
    delta = pack_buff_delta_from_row(row, ROW_ARG0, ROW_ARG3 + 1)
    ctx.self_buff = _merge_buff_delta(ctx.self_buff, delta)


def op_self_debuff(ctx: StageCtx, row: tuple[int, ...]) -> None:
    delta = pack_buff_delta_from_row(row, ROW_ARG0, ROW_ARG3 + 1)
    ctx.self_buff = _merge_buff_delta(ctx.self_buff, delta)


def op_enemy_debuff(ctx: StageCtx, row: tuple[int, ...]) -> None:
    delta = pack_buff_delta_from_row(row, ROW_ARG0, ROW_ARG3 + 1)
    ctx.enemy_buff = _merge_buff_delta(ctx.enemy_buff, delta)


def op_apply_active_buff(ctx: StageCtx, row: tuple[int, ...]) -> None:
    buff_id = row[ROW_ARG0]
    if buff_id <= 0:
        raise RuntimeError(f"active buff row has invalid buff_id {buff_id}")
    duration = _active_buff_duration_from_reduce(row[ROW_ARG1], row[ROW_ARG2], row[ROW_ARG3])
    target = row[ROW_TARGET]
    if target == TARGET_SELF:
        _set_active_buff_request(ctx, "self", buff_id, duration)
    elif target == TARGET_ENEMY:
        _set_active_buff_request(ctx, "enemy", buff_id, duration)
    else:
        raise RuntimeError(f"active buff row has unsupported target_type {target}")


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
        ctx.self_buff = _merge_buff_delta(ctx.self_buff, pack_buff_delta_from_row(row, ROW_ARG0, ROW_ARG0 + 1))
        ctx.heal_energy += row[ROW_ARG1]


def op_on_skill_element_buff(ctx: StageCtx, row: tuple[int, ...]) -> None:
    if ctx.skill_element == row[ROW_ARG0]:
        ctx.self_buff = _merge_buff_delta(ctx.self_buff, pack_buff_delta_from_row(row, ROW_ARG1, ROW_ARG1 + 1))


def op_bloodline_entry(ctx: StageCtx, row: tuple[int, ...]) -> None:
    if ctx.actor_bloodline == row[ROW_ARG0]:
        ctx.enemy_buff = _merge_buff_delta(ctx.enemy_buff, pack_buff_delta_from_row(row, ROW_ARG1, ROW_ARG1 + 1))


def op_contract_entry(ctx: StageCtx, row: tuple[int, ...]) -> None:
    ctx.self_buff = _merge_buff_delta(ctx.self_buff, pack_buff_delta_from_row(row, ROW_ARG0, ROW_ARG0 + 1))
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
    ctx.self_buff = _merge_buff_delta(ctx.self_buff, packed)


def op_entry_self_buff_by_side_count(ctx: StageCtx, row: tuple[int, ...]) -> None:
    selector = row[ROW_ARG0]
    count = _unpack_skill_count(ctx.side_element_counts, Element(selector))
    if row[ROW_ARG2]:
        count = min(count, 1)
    ctx.self_buff = _merge_buff_delta(
        ctx.self_buff,
        scale_buff_delta(row[ROW_ARG1], count),
    )


def op_entry_self_buff_by_fainted_count(ctx: StageCtx, row: tuple[int, ...]) -> None:
    ctx.self_buff = _merge_buff_delta(
        ctx.self_buff,
        scale_buff_delta(row[ROW_ARG0], ctx.side_fainted_count),
    )


def op_global_cost_delta(ctx: StageCtx, row: tuple[int, ...]) -> None:
    if row[ROW_TARGET] in (TARGET_SELF, TARGET_ALLY, TARGET_TEAM):
        ctx.self_global_cost_delta += row[ROW_ARG0]
    else:
        ctx.enemy_global_cost_delta += row[ROW_ARG0]


def op_entry_self_buff_by_used_skill_count(ctx: StageCtx, row: tuple[int, ...]) -> None:
    count = _unpack_skill_count(ctx.side_skill_counts, Element(row[ROW_ARG0]))
    ctx.self_buff = _merge_buff_delta(
        ctx.self_buff,
        scale_buff_delta(row[ROW_ARG1], count),
    )


def op_entry_self_buff_by_source_count(ctx: StageCtx, row: tuple[int, ...]) -> None:
    count = entry_source_count(ctx, row[ROW_ARG0])
    ctx.self_buff = _merge_buff_delta(
        ctx.self_buff,
        scale_buff_delta(row[ROW_ARG1], count),
    )


def op_entry_self_buff_if_energy(ctx: StageCtx, row: tuple[int, ...]) -> None:
    observed = ctx.actor_energy if row[ROW_ARG0] == 1 else ctx.target_energy
    if observed != row[ROW_ARG1]:
        return
    ctx.self_buff = _merge_buff_delta(ctx.self_buff, row[ROW_ARG2])


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


def _active_buff_duration_from_reduce(reduce_type: int, param0: int, param1: int) -> int:
    if reduce_type == 13 and param0 == 999 and param1 == 0:
        return 0
    raise RuntimeError(
        f"unsupported active buff reduce rule reduce_type={reduce_type} "
        f"params=({param0}, {param1})"
    )


def _set_active_buff_request(ctx: StageCtx, target: str, buff_id: int, duration: int) -> None:
    id_attr = f"{target}_active_buff_id"
    duration_attr = f"{target}_active_buff_duration"
    existing = getattr(ctx, id_attr)
    existing_duration = getattr(ctx, duration_attr)
    if existing and (existing != buff_id or existing_duration != duration):
        raise RuntimeError(
            f"multiple active buff requests for {target}: "
            f"{existing}/{existing_duration} and {buff_id}/{duration}"
        )
    setattr(ctx, id_attr, buff_id)
    setattr(ctx, duration_attr, duration)
