"""Kernel effect dispatch — handler array indexed by compiler-assigned IDs.

The compiler (effect_codegen + artifact) assigns a handler index to each
effect row based on pak data analysis.  The kernel just indexes into
HANDLERS[] — no classification, no dicts, no keyword matching here.

To add a new handler:
1. Add the function in the appropriate op_*.py module.
2. Append it to HANDLERS below and note its index.
3. Update effect_codegen.py to assign that index to the right pak prefix families.
"""

from __future__ import annotations

from roco.engine.kernel.ctx import StageCtx
from roco.engine.kernel.op_rows import ROW_TAG, ROW_TIMING, ROW_COND, condition_matches

from roco.engine.kernel.op_rows import (  # noqa: F401
    TIMING_AFTER_MOVE, TIMING_BATTLE_START, TIMING_BEFORE_MOVE,
    TIMING_CALC_DAMAGE, TIMING_CHARGE, TIMING_CHECK_HIT,
    TIMING_ENEMY_SWITCH, TIMING_FAINT, TIMING_PASSIVE_COND,
    TIMING_PASSIVE_PERSIST, TIMING_SWITCH_IN, TIMING_SWITCH_OUT,
    TIMING_TAKE_DAMAGE, TIMING_TURN_END, TIMING_TURN_START,
)

from roco.engine.kernel.op_mods import (
    op_auto_switch_on_zero_energy, op_bloodline_entry, op_borrow_team_skill,
    op_carry_skill_power_bonus, op_cleanse, op_contract_entry,
    op_counter_accumulate_transform, op_counter_attack, op_counter_success_speed_priority,
    op_damage, op_damage_mod_bloodline, op_damage_mod_non_light,
    op_damage_mod_non_stab, op_damage_mod_non_weakness, op_damage_reduction,
    op_debuff_extra_layers, op_devotion_grant_random, op_dispel_buffs,
    op_dispel_debuffs, op_enemy_debuff, op_energy_drain_by_cost_diff,
    op_entry_buff_per_skill_count, op_exchange_hp_ratio, op_exchange_moves,
    op_first_strike_hit_count, op_force_enemy_switch, op_force_switch,
    op_hit_count_delta, op_hit_count_per_poison, op_interrupt,
    op_mirror_enemy_buffs, op_next_attack_mod, op_on_interrupt_cooldown,
    op_on_skill_element_buff, op_on_skill_element_hit_count,
    op_on_super_effective_buff, op_permanent_mod, op_power_by_status_count_elements,
    op_power_dynamic, op_self_buff, op_self_debuff, op_skill_mod,
    op_specific_skill_power_bonus, op_stat_scale_hits_per_hp_lost,
    op_team_synergy_bug_swarm_attack, op_transfer_mods, op_charge_cost_reduce,
)
from roco.engine.kernel.op_resources import (
    op_anti_heal, op_enemy_energy_cost_up, op_enemy_lose_energy,
    op_enemy_switch_self_cost_reduce, op_energy_all_in, op_energy_regen_per_turn,
    op_entry_energy_from_counter_count, op_entry_energy_from_element_count,
    op_entry_self_damage, op_grant_life_drain, op_heal_energy, op_heal_hp,
    op_heal_on_grass_skill, op_hp_for_energy, op_leave_energy_refill,
    op_leave_heal_ally, op_life_drain, op_low_cost_skill_power_bonus,
    op_on_skill_element_cost_reduce, op_on_skill_element_enemy_energy,
    op_passive_energy_reduce, op_skill_cost_reduction_type,
    op_steal_all_enemy_energy, op_steal_energy,
)
from roco.engine.kernel.op_marks import (
    op_attack_mark, op_charge_mark, op_consume_marks_heal,
    op_convert_poison_to_mark, op_dispel_enemy_marks, op_dispel_marks,
    op_dragon_mark, op_meteor_mark, op_moisture_mark, op_momentum_mark,
    op_poison_mark, op_slow_mark, op_sluggish_mark, op_solar_mark,
    op_spirit_mark, op_thorn_mark, op_wind_mark,
)
from roco.engine.kernel.op_status import (
    op_burn, op_freeze, op_leech, op_on_skill_element_burn,
    op_on_skill_element_freeze, op_on_skill_element_poison,
    op_poison, op_poison_on_skill_apply, op_weather,
)
from roco.engine.kernel.op_cute import (
    op_cute_both, op_cute_clear_self, op_cute_enemy_gain, op_cute_gain,
    op_cute_hit_per_stack, op_cute_if_power_bonus, op_cute_lethal_shield,
    op_cute_bench_cost_reduce, op_cute_on_gain_cost_reduce,
    op_cute_on_gain_power_perm, op_cute_on_gain_speed_perm,
    op_cute_team_power, op_cute_transfer,
)


def _noop(_ctx: StageCtx, _row: tuple[int, ...]) -> None:
    pass


# Handler array — indexed by compiler-assigned handler IDs.
# Index 0 is always noop. The compiler assigns indices via effect_codegen.
# DO NOT reorder — indices are baked into compiled catalogs.
HANDLERS: tuple[..., ...] = (
    _noop,                          # 0
    op_damage,                      # 1
    op_life_drain,                  # 2
    op_damage_reduction,            # 3
    op_self_buff,                   # 4
    op_enemy_debuff,                # 5
    op_self_debuff,                 # 6
    op_burn,                        # 7
    op_poison,                      # 8
    op_freeze,                      # 9
    op_leech,                       # 10
    op_heal_hp,                     # 11
    op_heal_energy,                 # 12
    op_steal_energy,                # 13
    op_enemy_lose_energy,           # 14
    op_force_switch,                # 15
    op_weather,                     # 16
    op_cleanse,                     # 17
    op_power_dynamic,               # 18
    op_enemy_energy_cost_up,        # 19
    op_passive_energy_reduce,       # 20
    op_hit_count_delta,             # 21
    op_cute_gain,                   # 22
    op_cute_enemy_gain,             # 23
    op_cute_both,                   # 24
    op_force_enemy_switch,          # 25
    op_counter_attack,              # 26
    op_interrupt,                   # 27
    op_energy_all_in,               # 28
    op_hp_for_energy,               # 29
    op_anti_heal,                   # 30
    # --- Mark handlers (31-43) ---
    op_poison_mark,                 # 31
    op_moisture_mark,               # 32
    op_dragon_mark,                 # 33
    op_wind_mark,                   # 34
    op_charge_mark,                 # 35
    op_solar_mark,                  # 36
    op_attack_mark,                 # 37
    op_slow_mark,                   # 38
    op_sluggish_mark,               # 39
    op_spirit_mark,                 # 40
    op_meteor_mark,                 # 41
    op_thorn_mark,                  # 42
    op_momentum_mark,               # 43
    op_dispel_enemy_marks,          # 44
    op_consume_marks_heal,          # 45
    op_dispel_marks,                # 46
    op_convert_poison_to_mark,      # 47
    op_permanent_mod,               # 48
    op_grant_life_drain,            # 49
    op_energy_regen_per_turn,       # 50
)

HANDLER_COUNT = len(HANDLERS)

KERNEL_SUPPORTED_TAGS = tuple(range(HANDLER_COUNT))


def run_skill_timing(
    effect_rows: tuple[tuple[int, ...], ...],
    effect_range: tuple[int, int],
    timing: int,
    ctx: StageCtx,
) -> None:
    start, end = effect_range
    for idx in range(start, end):
        row = effect_rows[idx]
        if row[ROW_TIMING] == timing and condition_matches(row[ROW_COND], ctx):
            handler_idx = row[ROW_TAG]
            if 0 < handler_idx < HANDLER_COUNT:
                HANDLERS[handler_idx](ctx, row)
