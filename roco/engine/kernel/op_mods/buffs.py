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
from roco.engine.kernel.op_meta import handles_buff, handles_prefix
from roco.engine.kernel.op_rows import (
    ROW_ARG0,
    ROW_ARG1,
    ROW_ARG2,
    ROW_ARG3,
    ROW_TARGET,
    TARGET_ALLY,
    TARGET_SELF,
    TARGET_TEAM,
)

COUNT_FAINTED_ALLY = -1


@handles_prefix([
    ("BFT_KILL_BUFF", "ON_KILL"),
    ("BFT_ENTER_BATTLE", "ENTRY_STATUS"),
])
@handles_buff([
    ("BFT_ATTR_CHANGE", "STAT_MOD"),
    ("BFT_BAN", "LOCK_SWITCH"),
    ("BFT_SKILL_BAN", "BOSS_STUN"),
    ("BFT_RELAY", "NEXT_PET"),
    ("BFT_CAST_REPEAT_SKILL", "DOUBLE_ACTION"),
    ("BFT_CAST_SKILL_AFTER_ATTACK", "ON_HIT_REACTION"),
    ("BFT_INC_DAM_BY_BUFF", "ELEMENT_VULN"),
    ("BFT_RECORD_CAST_SKILL", "TEST_28"),
    ("BFT_CHANGE_CATCH_VALUE", "ENTRY_AMBUSH"),
    ("BFT_BUFF_AFTER_SKILL", "ELEMENT_TRIGGER"),
    ("BFT_FIELD_REDUSE_COST", "DUCK"),
    ("BFT_CHECK_HP", "HP_CONDITIONAL"),
    ("BFT_ASSIGN_ATTACK_FIRST", "QUICK_START"),
    ("BFT_SPIKES", "TURN_END_TRANSFORM"),
    ("BFT_DETECT_ENEMY_SKILLS", "DREAM"),
    ("BFT_SKILL_CHANGE", "SKILL_COPY"),
    ("BFT_TARGET_HAS_BUFF", "CHAR_SPECIFIC_A"),
    ("BFT_STRENGTHEN_THE_SKILL", "CONDITIONAL_TRIGGER"),
    ("BFT_SIXTY_SEVEN", "COUNTER_REWARD"),
    ("BFT_SEVENTY_TWO", "OTTER"),
    ("BFT_SEVENTY_THREE", "TEAM_ON_DEATH"),
    ("BFT_SEVENTY_FIVE", "DOUBLE_TRIGGER"),
    ("BFT_SEVENTY_SIX", "SLEEPWALK"),
    ("BFT_SEVENTY_SEVEN", "SLOT_PRIORITY"),
    ("BFT_SEVENTY_NINE", "LANTERN"),
    ("BFT_EIGHTY", "CYCLOPS"),
    ("BFT_EIGHTY_THREE", "MIRROR_PRIORITY"),
    ("BFT_EIGHTY_FOUR", "FEYNMAN"),
    ("BFT_EIGHTY_SIX", "CHAR_SPECIFIC_B"),
    ("BFT_EIGHTY_EIGHT", "CHARGE"),
    ("BFT_EIGHTY_NINE", "REFRACT"),
    ("BFT_NINETY_TWO", "FREEZE_LOCK"),
    ("BFT_NINETY_THREE", "ENTRY_FIRST_TURN"),
    ("BFT_O_ONE", "EXTEND_ENTRY"),
    ("BFT_O_THREE", "DIFF_SKILL_COST"),
    ("BFT_O_FOUR", "MAGIC_KILLER"),
    ("BFT_O_FIVE", "SKILL_CHECK"),
    ("BFT_O_SIX", "POSITION_COST"),
    ("BFT_O_TEN", "MARK_NO_DECAY"),
    ("BFT_O_ELEVEN", "BURN_REVERSE"),
    ("BFT_O_TWELVE", "COVER"),
    ("BFT_O_FOURTEEN", "CAP_RAISE"),
    ("BFT_O_SEVENTEEN", "SLOT_MOD"),
    ("BFT_O_EIGHTEEN", "RETURN"),
    ("BFT_O_NINETEEN", "FIRST_USE_POWER"),
    ("BFT_O_TWENTY", "SIDE_COST"),
    ("BFT_O_TWENTYONE", "TEST"),
    ("BFT_O_THIRTY", "ALERT"),
    ("BFT_O_THIRTYTWO", "BORROW"),
    ("BFT_O_THIRTYSIX", "CUTE_NO_CAP"),
    ("BFT_O_FORTYTWO", "CUTE_CHAIN"),
])
def op_self_buff(ctx: StageCtx, row: tuple[int, ...]) -> None:
    delta = pack_buff_delta_from_row(row, ROW_ARG0, ROW_ARG3 + 1)
    ctx.self_buff = _merge_buff_delta(ctx.self_buff, delta)


def op_self_debuff(ctx: StageCtx, row: tuple[int, ...]) -> None:
    delta = pack_buff_delta_from_row(row, ROW_ARG0, ROW_ARG3 + 1)
    ctx.self_buff = _merge_buff_delta(ctx.self_buff, delta)


def op_enemy_debuff(ctx: StageCtx, row: tuple[int, ...]) -> None:
    delta = pack_buff_delta_from_row(row, ROW_ARG0, ROW_ARG3 + 1)
    ctx.enemy_buff = _merge_buff_delta(ctx.enemy_buff, delta)


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
    if selector == COUNT_FAINTED_ALLY:
        count = ctx.side_fainted_count
    else:
        count = _unpack_skill_count(ctx.side_element_counts, Element(selector))
    if row[ROW_ARG2]:
        count = min(count, 1)
    ctx.self_buff = _merge_buff_delta(
        ctx.self_buff,
        scale_buff_delta(row[ROW_ARG1], count),
    )


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
