"""Fixed-kernel effect op table over integer effect rows."""

from __future__ import annotations

from roco.engine.kernel.ctx import StageCtx
from roco.engine.kernel.op_cute import (
    op_cute_both,
    op_cute_clear_self,
    op_cute_enemy_gain,
    op_cute_gain,
    op_cute_hit_per_stack,
    op_cute_if_power_bonus,
    op_cute_lethal_shield,
    op_cute_bench_cost_reduce,
    op_cute_on_gain_cost_reduce,
    op_cute_on_gain_power_perm,
    op_cute_on_gain_speed_perm,
    op_cute_team_power,
    op_cute_transfer,
)
from roco.engine.kernel.op_marks import (
    op_attack_mark,
    op_charge_mark,
    op_consume_marks_heal,
    op_convert_poison_to_mark,
    op_dispel_enemy_marks,
    op_dispel_marks,
    op_dragon_mark,
    op_meteor_mark,
    op_moisture_mark,
    op_momentum_mark,
    op_poison_mark,
    op_sluggish_mark,
    op_slow_mark,
    op_solar_mark,
    op_spirit_mark,
    op_thorn_mark,
    op_wind_mark,
)
from roco.engine.kernel.op_mods import (
    op_auto_switch_on_zero_energy,
    op_bloodline_entry,
    op_borrow_team_skill,
    op_carry_skill_power_bonus,
    op_cleanse,
    op_contract_entry,
    op_counter_attack,
    op_counter_success_speed_priority,
    op_damage,
    op_damage_mod_bloodline,
    op_damage_mod_non_light,
    op_damage_mod_non_stab,
    op_damage_mod_non_weakness,
    op_damage_reduction,
    op_devotion_grant_random,
    op_dispel_buffs,
    op_dispel_debuffs,
    op_enemy_debuff,
    op_entry_buff_per_skill_count,
    op_energy_drain_by_cost_diff,
    op_exchange_hp_ratio,
    op_exchange_moves,
    op_first_strike_hit_count,
    op_force_enemy_switch,
    op_force_switch,
    op_hit_count_delta,
    op_hit_count_per_poison,
    op_interrupt,
    op_mirror_enemy_buffs,
    op_next_attack_mod,
    op_on_interrupt_cooldown,
    op_on_skill_element_buff,
    op_on_skill_element_hit_count,
    op_on_super_effective_buff,
    op_permanent_mod,
    op_power_dynamic,
    op_power_by_status_count_elements,
    op_specific_skill_power_bonus,
    op_self_buff,
    op_self_debuff,
    op_skill_mod,
    op_stat_scale_hits_per_hp_lost,
    op_team_synergy_bug_swarm_attack,
    op_transfer_mods,
    op_charge_cost_reduce,
    op_counter_accumulate_transform,
    op_debuff_extra_layers,
)
from roco.engine.kernel.op_resources import (
    op_anti_heal,
    op_energy_all_in,
    op_energy_regen_per_turn,
    op_enemy_energy_cost_up,
    op_enemy_lose_energy,
    op_enemy_switch_self_cost_reduce,
    op_entry_energy_from_counter_count,
    op_entry_energy_from_element_count,
    op_entry_self_damage,
    op_grant_life_drain,
    op_heal_energy,
    op_heal_hp,
    op_heal_on_grass_skill,
    op_hp_for_energy,
    op_leave_energy_refill,
    op_leave_heal_ally,
    op_life_drain,
    op_low_cost_skill_power_bonus,
    op_on_skill_element_cost_reduce,
    op_on_skill_element_enemy_energy,
    op_passive_energy_reduce,
    op_skill_cost_reduction_type,
    op_steal_all_enemy_energy,
    op_steal_energy,
)
from roco.engine.kernel.op_rows import *  # noqa: F403
from roco.engine.kernel.op_status import (
    op_burn,
    op_freeze,
    op_leech,
    op_on_skill_element_burn,
    op_on_skill_element_freeze,
    op_on_skill_element_poison,
    op_poison,
    op_poison_on_skill_apply,
    op_weather,
)
from roco.engine.kernel.op_tags import *  # noqa: F403


def _op_unsupported(ctx: StageCtx, row: tuple[int, ...]) -> None:
    raise NotImplementedError(row[ROW_TAG])  # noqa: F405


_TABLE = [_op_unsupported] * (MAX_TAG + 1)  # noqa: F405
_TABLE[TAG_DAMAGE] = op_damage  # noqa: F405
_TABLE[TAG_DAMAGE_REDUCTION] = op_damage_reduction  # noqa: F405
_TABLE[TAG_HEAL_HP] = op_heal_hp  # noqa: F405
_TABLE[TAG_HEAL_ENERGY] = op_heal_energy  # noqa: F405
_TABLE[TAG_STEAL_ENERGY] = op_steal_energy  # noqa: F405
_TABLE[TAG_ENEMY_LOSE_ENERGY] = op_enemy_lose_energy  # noqa: F405
_TABLE[TAG_LIFE_DRAIN] = op_life_drain  # noqa: F405
_TABLE[TAG_SELF_BUFF] = op_self_buff  # noqa: F405
_TABLE[TAG_SELF_DEBUFF] = op_self_debuff  # noqa: F405
_TABLE[TAG_ENEMY_DEBUFF] = op_enemy_debuff  # noqa: F405
_TABLE[TAG_FORCE_SWITCH] = op_force_switch  # noqa: F405
_TABLE[TAG_FORCE_ENEMY_SWITCH] = op_force_enemy_switch  # noqa: F405
_TABLE[TAG_COUNTER_ATTACK] = op_counter_attack  # noqa: F405
_TABLE[TAG_GRANT_LIFE_DRAIN] = op_grant_life_drain  # noqa: F405
_TABLE[TAG_AUTO_SWITCH_AFTER_ACTION] = op_force_switch  # noqa: F405
_TABLE[TAG_AUTO_SWITCH_ON_ZERO_ENERGY] = op_auto_switch_on_zero_energy  # noqa: F405
_TABLE[TAG_CLEANSE] = op_cleanse  # noqa: F405
_TABLE[TAG_PASSIVE_ENERGY_REDUCE] = op_passive_energy_reduce  # noqa: F405
_TABLE[TAG_CONVERT_POISON_TO_MARK] = op_convert_poison_to_mark  # noqa: F405
_TABLE[TAG_DISPEL_DEBUFFS] = op_dispel_debuffs  # noqa: F405
_TABLE[TAG_BURN] = op_burn  # noqa: F405
_TABLE[TAG_POISON] = op_poison  # noqa: F405
_TABLE[TAG_FREEZE] = op_freeze  # noqa: F405
_TABLE[TAG_LEECH] = op_leech  # noqa: F405
_TABLE[TAG_ENERGY_ALL_IN] = op_energy_all_in  # noqa: F405
_TABLE[TAG_WEATHER] = op_weather  # noqa: F405
_TABLE[TAG_MOISTURE_MARK] = op_moisture_mark  # noqa: F405
_TABLE[TAG_DRAGON_MARK] = op_dragon_mark  # noqa: F405
_TABLE[TAG_MOMENTUM_MARK] = op_momentum_mark  # noqa: F405
_TABLE[TAG_WIND_MARK] = op_wind_mark  # noqa: F405
_TABLE[TAG_CHARGE_MARK] = op_charge_mark  # noqa: F405
_TABLE[TAG_SOLAR_MARK] = op_solar_mark  # noqa: F405
_TABLE[TAG_ATTACK_MARK] = op_attack_mark  # noqa: F405
_TABLE[TAG_SLOW_MARK] = op_slow_mark  # noqa: F405
_TABLE[TAG_SPIRIT_MARK] = op_spirit_mark  # noqa: F405
_TABLE[TAG_METEOR_MARK] = op_meteor_mark  # noqa: F405
_TABLE[TAG_POISON_MARK] = op_poison_mark  # noqa: F405
_TABLE[TAG_THORN_MARK] = op_thorn_mark  # noqa: F405
_TABLE[TAG_SLUGGISH_MARK] = op_sluggish_mark  # noqa: F405
_TABLE[TAG_DISPEL_ENEMY_MARKS] = op_dispel_enemy_marks  # noqa: F405
_TABLE[TAG_CONSUME_MARKS_HEAL] = op_consume_marks_heal  # noqa: F405
_TABLE[TAG_STEAL_MARKS] = op_dispel_enemy_marks  # noqa: F405
_TABLE[TAG_AGILITY] = op_self_buff  # noqa: F405
_TABLE[TAG_INTERRUPT] = op_interrupt  # noqa: F405
_TABLE[TAG_DISPEL_MARKS] = op_dispel_marks  # noqa: F405
_TABLE[TAG_DISPEL_BUFFS] = op_dispel_buffs  # noqa: F405
_TABLE[TAG_POWER_DYNAMIC] = op_power_dynamic  # noqa: F405
_TABLE[TAG_PERMANENT_MOD] = op_permanent_mod  # noqa: F405
_TABLE[TAG_NEXT_ATTACK_MOD] = op_next_attack_mod  # noqa: F405
_TABLE[TAG_HP_FOR_ENERGY] = op_hp_for_energy  # noqa: F405
_TABLE[TAG_ENERGY_REGEN_PER_TURN] = op_energy_regen_per_turn  # noqa: F405
_TABLE[TAG_LEAVE_ENERGY_REFILL] = op_leave_energy_refill  # noqa: F405
_TABLE[TAG_LEAVE_HEAL_ALLY] = op_leave_heal_ally  # noqa: F405
_TABLE[TAG_ENEMY_SWITCH_SELF_COST_REDUCE] = op_enemy_switch_self_cost_reduce  # noqa: F405
_TABLE[TAG_ON_INTERRUPT_COOLDOWN] = op_on_interrupt_cooldown  # noqa: F405
_TABLE[TAG_STEAL_ALL_ENEMY_ENERGY] = op_steal_all_enemy_energy  # noqa: F405
_TABLE[TAG_ENEMY_ENERGY_COST_UP] = op_enemy_energy_cost_up  # noqa: F405
_TABLE[TAG_ENEMY_ALL_COST_UP] = op_enemy_energy_cost_up  # noqa: F405
_TABLE[TAG_TRANSFER_MODS] = op_transfer_mods  # noqa: F405
_TABLE[TAG_MIRROR_ENEMY_BUFFS] = op_mirror_enemy_buffs  # noqa: F405
_TABLE[TAG_COUNTER_SUCCESS_SPEED_PRIORITY] = op_counter_success_speed_priority  # noqa: F405
_TABLE[TAG_TEAM_SYNERGY_BUG_SWARM_ATTACK] = op_team_synergy_bug_swarm_attack  # noqa: F405
_TABLE[TAG_SKILL_MOD] = op_skill_mod  # noqa: F405
_TABLE[TAG_ENTRY_SELF_DAMAGE] = op_entry_self_damage  # noqa: F405
_TABLE[TAG_FIRST_STRIKE_POWER_BONUS] = op_power_dynamic  # noqa: F405
_TABLE[TAG_FIRST_STRIKE_HIT_COUNT] = op_first_strike_hit_count  # noqa: F405
_TABLE[TAG_HIT_COUNT_PER_POISON] = op_hit_count_per_poison  # noqa: F405
_TABLE[TAG_STAT_SCALE_HITS_PER_HP_LOST] = op_stat_scale_hits_per_hp_lost  # noqa: F405
_TABLE[TAG_DAMAGE_MOD_NON_STAB] = op_damage_mod_non_stab  # noqa: F405
_TABLE[TAG_DAMAGE_MOD_NON_LIGHT] = op_damage_mod_non_light  # noqa: F405
_TABLE[TAG_DAMAGE_MOD_NON_WEAKNESS] = op_damage_mod_non_weakness  # noqa: F405
_TABLE[TAG_DAMAGE_MOD_POLLUTANT_BLOOD] = op_damage_mod_bloodline  # noqa: F405
_TABLE[TAG_DAMAGE_MOD_LEADER_BLOOD] = op_damage_mod_bloodline  # noqa: F405
_TABLE[TAG_LOW_COST_SKILL_POWER_BONUS] = op_low_cost_skill_power_bonus  # noqa: F405
_TABLE[TAG_SPECIFIC_SKILL_POWER_BONUS] = op_specific_skill_power_bonus  # noqa: F405
_TABLE[TAG_ON_SUPER_EFFECTIVE_BUFF] = op_on_super_effective_buff  # noqa: F405
_TABLE[TAG_HEAL_ON_GRASS_SKILL] = op_heal_on_grass_skill  # noqa: F405
_TABLE[TAG_SKILL_COST_REDUCTION_TYPE] = op_skill_cost_reduction_type  # noqa: F405
_TABLE[TAG_ON_SKILL_ELEMENT_BUFF] = op_on_skill_element_buff  # noqa: F405
_TABLE[TAG_ON_SKILL_ELEMENT_POISON] = op_on_skill_element_poison  # noqa: F405
_TABLE[TAG_ON_SKILL_ELEMENT_BURN] = op_on_skill_element_burn  # noqa: F405
_TABLE[TAG_ON_SKILL_ELEMENT_FREEZE] = op_on_skill_element_freeze  # noqa: F405
_TABLE[TAG_ON_SKILL_ELEMENT_HIT_COUNT] = op_on_skill_element_hit_count  # noqa: F405
_TABLE[TAG_ENTRY_ENERGY_FROM_ELEMENT_COUNT] = op_entry_energy_from_element_count  # noqa: F405
_TABLE[TAG_ENTRY_ENERGY_FROM_COUNTER_COUNT] = op_entry_energy_from_counter_count  # noqa: F405
_TABLE[TAG_ENTRY_BUFF_PER_SKILL_COUNT] = op_entry_buff_per_skill_count  # noqa: F405
_TABLE[TAG_ENERGY_DRAIN_BY_COST_DIFF] = op_energy_drain_by_cost_diff  # noqa: F405
_TABLE[TAG_CHARGE_COST_REDUCE] = op_charge_cost_reduce  # noqa: F405
_TABLE[TAG_COUNTER_ACCUMULATE_TRANSFORM] = op_counter_accumulate_transform  # noqa: F405
_TABLE[TAG_EXCHANGE_MOVES] = op_exchange_moves  # noqa: F405
_TABLE[TAG_EXCHANGE_HP_RATIO] = op_exchange_hp_ratio  # noqa: F405
_TABLE[TAG_BORROW_TEAM_SKILL] = op_borrow_team_skill  # noqa: F405
_TABLE[TAG_HIT_COUNT_DELTA] = op_hit_count_delta  # noqa: F405
_TABLE[TAG_POWER_BY_STATUS_COUNT_ELEMENTS] = op_power_by_status_count_elements  # noqa: F405
_TABLE[TAG_DEBUFF_EXTRA_LAYERS] = op_debuff_extra_layers  # noqa: F405
_TABLE[TAG_ANTI_HEAL] = op_anti_heal  # noqa: F405
_TABLE[TAG_ON_SKILL_ELEMENT_COST_REDUCE] = op_on_skill_element_cost_reduce  # noqa: F405
_TABLE[TAG_ON_SKILL_ELEMENT_ENEMY_ENERGY] = op_on_skill_element_enemy_energy  # noqa: F405
_TABLE[TAG_POISON_ON_SKILL_APPLY] = op_poison_on_skill_apply  # noqa: F405
_TABLE[TAG_CARRY_SKILL_POWER_BONUS] = op_carry_skill_power_bonus  # noqa: F405
_TABLE[TAG_CARRY_SKILL_COST_REDUCE] = op_skill_cost_reduction_type  # noqa: F405
_TABLE[TAG_BLOODLINE_ENTRY] = op_bloodline_entry  # noqa: F405
_TABLE[TAG_DEVOTION_GRANT_RANDOM] = op_devotion_grant_random  # noqa: F405
_TABLE[TAG_CONTRACT_ENTRY] = op_contract_entry  # noqa: F405
_TABLE[TAG_CUTE_GAIN] = op_cute_gain  # noqa: F405
_TABLE[TAG_CUTE_ENEMY_GAIN] = op_cute_enemy_gain  # noqa: F405
_TABLE[TAG_CUTE_BOTH] = op_cute_both  # noqa: F405
_TABLE[TAG_CUTE_TRANSFER] = op_cute_transfer  # noqa: F405
_TABLE[TAG_CUTE_CLEAR_SELF] = op_cute_clear_self  # noqa: F405
_TABLE[TAG_CUTE_IF_POWER_BONUS] = op_cute_if_power_bonus  # noqa: F405
_TABLE[TAG_CUTE_ON_GAIN_POWER_PERM] = op_cute_on_gain_power_perm  # noqa: F405
_TABLE[TAG_CUTE_ON_GAIN_COST_REDUCE] = op_cute_on_gain_cost_reduce  # noqa: F405
_TABLE[TAG_CUTE_ON_GAIN_SPEED_PERM] = op_cute_on_gain_speed_perm  # noqa: F405
_TABLE[TAG_CUTE_TEAM_POWER] = op_cute_team_power  # noqa: F405
_TABLE[TAG_CUTE_LETHAL_SHIELD] = op_cute_lethal_shield  # noqa: F405
_TABLE[TAG_CUTE_HIT_PER_STACK] = op_cute_hit_per_stack  # noqa: F405
_TABLE[TAG_CUTE_BENCH_COST_REDUCE] = op_cute_bench_cost_reduce  # noqa: F405

OP_TABLE = tuple(_TABLE)
KERNEL_SUPPORTED_TAGS = tuple(
    idx for idx, op in enumerate(OP_TABLE)
    if op is not _op_unsupported
)


def run_skill_timing(effect_rows: tuple[tuple[int, ...], ...], effect_range: tuple[int, int], timing: int, ctx: StageCtx) -> None:
    start, end = effect_range
    for idx in range(start, end):
        row = effect_rows[idx]
        if row[ROW_TIMING] == timing and condition_matches(row[ROW_COND], ctx):  # noqa: F405
            OP_TABLE[row[ROW_TAG]](ctx, row)  # noqa: F405
