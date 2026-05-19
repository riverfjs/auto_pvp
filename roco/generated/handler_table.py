# Auto-generated from handler_registry.json — do not edit.
# Regenerate with: uv run python -m roco.compiler.gen_prefix_map

from roco.engine.kernel.ctx import StageCtx

from roco.engine.kernel.op_mods.damage import (
    op_damage,
    op_damage_reduction,
    op_damage_mod_non_stab,
    op_damage_mod_non_light,
    op_damage_mod_non_weakness,
    op_damage_mod_leader_blood,
    op_damage_mod_pollutant,
)
from roco.engine.kernel.op_mods.buffs import (
    op_self_buff,
    op_enemy_debuff,
    op_self_debuff,
    op_cleanse,
    op_permanent_mod,
    op_next_attack_mod,
    op_on_skill_element_buff,
    op_on_super_effective_buff,
    op_mirror_enemy_buffs,
    op_dispel_buffs,
    op_dispel_debuffs,
    op_debuff_extra_layers,
    op_team_synergy_bug_swarm_attack,
    op_entry_buff_per_skill_count,
    op_contract_entry,
    op_bloodline_entry,
)
from roco.engine.kernel.op_mods.skill import (
    op_power_dynamic,
    op_skill_mod,
    op_carry_skill_power_bonus,
    op_specific_skill_power_bonus,
    op_transfer_mods,
    op_exchange_hp_ratio,
    op_exchange_moves,
    op_power_by_status_count_elements,
    op_borrow_team_skill,
)
from roco.engine.kernel.op_mods.combat import (
    op_force_switch,
    op_hit_count_delta,
    op_force_enemy_switch,
    op_counter_attack,
    op_interrupt,
    op_on_skill_element_hit_count,
    op_counter_accumulate_transform,
    op_counter_success_speed_priority,
    op_first_strike_hit_count,
    op_stat_scale_hits_per_hp_lost,
    op_hit_count_per_poison,
    op_auto_switch_on_zero_energy,
    op_devotion_grant_random,
    op_charge_cost_reduce,
    op_energy_drain_by_cost_diff,
    op_on_interrupt_cooldown,
    op_set_self_cooldown,
    op_priority_next_delta,
)
from roco.engine.kernel.op_resources import (
    op_life_drain,
    op_heal_hp,
    op_heal_energy,
    op_steal_energy,
    op_enemy_lose_energy,
    op_enemy_energy_cost_up,
    op_passive_energy_reduce,
    op_energy_all_in,
    op_hp_for_energy,
    op_anti_heal,
    op_grant_life_drain,
    op_energy_regen_per_turn,
    op_skill_cost_reduction_type,
    op_on_skill_element_cost_reduce,
    op_on_skill_element_enemy_energy,
    op_entry_self_damage,
    op_heal_on_grass_skill,
    op_low_cost_skill_power_bonus,
    op_leave_heal_ally,
    op_leave_energy_refill,
    op_steal_all_enemy_energy,
    op_enemy_switch_self_cost_reduce,
    op_entry_energy_from_element_count,
    op_entry_energy_from_counter_count,
)
from roco.engine.kernel.op_marks import (
    op_poison_mark,
    op_moisture_mark,
    op_dragon_mark,
    op_wind_mark,
    op_charge_mark,
    op_solar_mark,
    op_attack_mark,
    op_slow_mark,
    op_sluggish_mark,
    op_spirit_mark,
    op_meteor_mark,
    op_thorn_mark,
    op_momentum_mark,
    op_dispel_enemy_marks,
    op_consume_marks_heal,
    op_dispel_marks,
    op_convert_poison_to_mark,
    op_dispel_marks_to_burn,
)
from roco.engine.kernel.op_status import (
    op_burn,
    op_poison,
    op_freeze,
    op_leech,
    op_weather,
    op_on_skill_element_burn,
    op_on_skill_element_freeze,
    op_on_skill_element_poison,
    op_poison_on_skill_apply,
)
from roco.engine.kernel.op_cute import (
    op_cute_gain,
    op_cute_enemy_gain,
    op_cute_both,
    op_cute_transfer,
    op_cute_clear_self,
    op_cute_if_power_bonus,
    op_cute_on_gain_power_perm,
    op_cute_on_gain_cost_reduce,
    op_cute_on_gain_speed_perm,
    op_cute_team_power,
    op_cute_lethal_shield,
    op_cute_hit_per_stack,
    op_cute_bench_cost_reduce,
)


def _noop(_ctx: StageCtx, _row: tuple[int, ...]) -> None:
    pass


HANDLERS: tuple = (
    _noop,  # 0
    op_damage,  # 1
    op_life_drain,  # 2
    op_damage_reduction,  # 3
    op_self_buff,  # 4
    op_enemy_debuff,  # 5
    op_self_debuff,  # 6
    op_burn,  # 7
    op_poison,  # 8
    op_freeze,  # 9
    op_leech,  # 10
    op_heal_hp,  # 11
    op_heal_energy,  # 12
    op_steal_energy,  # 13
    op_enemy_lose_energy,  # 14
    op_force_switch,  # 15
    op_weather,  # 16
    op_cleanse,  # 17
    op_power_dynamic,  # 18
    op_enemy_energy_cost_up,  # 19
    op_passive_energy_reduce,  # 20
    op_hit_count_delta,  # 21
    op_cute_gain,  # 22
    op_cute_enemy_gain,  # 23
    op_cute_both,  # 24
    op_force_enemy_switch,  # 25
    op_counter_attack,  # 26
    op_interrupt,  # 27
    op_energy_all_in,  # 28
    op_hp_for_energy,  # 29
    op_anti_heal,  # 30
    op_poison_mark,  # 31
    op_moisture_mark,  # 32
    op_dragon_mark,  # 33
    op_wind_mark,  # 34
    op_charge_mark,  # 35
    op_solar_mark,  # 36
    op_attack_mark,  # 37
    op_slow_mark,  # 38
    op_sluggish_mark,  # 39
    op_spirit_mark,  # 40
    op_meteor_mark,  # 41
    op_thorn_mark,  # 42
    op_momentum_mark,  # 43
    op_dispel_enemy_marks,  # 44
    op_consume_marks_heal,  # 45
    op_dispel_marks,  # 46
    op_convert_poison_to_mark,  # 47
    op_permanent_mod,  # 48
    op_grant_life_drain,  # 49
    op_energy_regen_per_turn,  # 50
    op_skill_mod,  # 51
    op_next_attack_mod,  # 52
    op_damage_mod_non_stab,  # 53
    op_damage_mod_non_light,  # 54
    op_damage_mod_non_weakness,  # 55
    op_damage_mod_leader_blood,  # 56
    op_damage_mod_pollutant,  # 57
    op_carry_skill_power_bonus,  # 58
    op_specific_skill_power_bonus,  # 59
    op_on_skill_element_buff,  # 60
    op_on_skill_element_hit_count,  # 61
    op_on_super_effective_buff,  # 62
    op_counter_accumulate_transform,  # 63
    op_counter_success_speed_priority,  # 64
    op_first_strike_hit_count,  # 65
    op_mirror_enemy_buffs,  # 66
    op_transfer_mods,  # 67
    op_dispel_buffs,  # 68
    op_dispel_debuffs,  # 69
    op_exchange_hp_ratio,  # 70
    op_exchange_moves,  # 71
    op_debuff_extra_layers,  # 72
    op_stat_scale_hits_per_hp_lost,  # 73
    op_hit_count_per_poison,  # 74
    op_power_by_status_count_elements,  # 75
    op_team_synergy_bug_swarm_attack,  # 76
    op_auto_switch_on_zero_energy,  # 77
    op_entry_buff_per_skill_count,  # 78
    op_devotion_grant_random,  # 79
    op_contract_entry,  # 80
    op_bloodline_entry,  # 81
    op_charge_cost_reduce,  # 82
    op_energy_drain_by_cost_diff,  # 83
    op_on_interrupt_cooldown,  # 84
    op_borrow_team_skill,  # 85
    op_skill_cost_reduction_type,  # 86
    op_on_skill_element_cost_reduce,  # 87
    op_on_skill_element_enemy_energy,  # 88
    op_entry_self_damage,  # 89
    op_heal_on_grass_skill,  # 90
    op_low_cost_skill_power_bonus,  # 91
    op_leave_heal_ally,  # 92
    op_leave_energy_refill,  # 93
    op_steal_all_enemy_energy,  # 94
    op_enemy_switch_self_cost_reduce,  # 95
    op_entry_energy_from_element_count,  # 96
    op_entry_energy_from_counter_count,  # 97
    op_on_skill_element_burn,  # 98
    op_on_skill_element_freeze,  # 99
    op_on_skill_element_poison,  # 100
    op_poison_on_skill_apply,  # 101
    op_cute_transfer,  # 102
    op_cute_clear_self,  # 103
    op_cute_if_power_bonus,  # 104
    op_cute_on_gain_power_perm,  # 105
    op_cute_on_gain_cost_reduce,  # 106
    op_cute_on_gain_speed_perm,  # 107
    op_cute_team_power,  # 108
    op_cute_lethal_shield,  # 109
    op_cute_hit_per_stack,  # 110
    op_cute_bench_cost_reduce,  # 111
    op_dispel_marks_to_burn,  # 112
    op_set_self_cooldown,  # 113
    op_priority_next_delta,  # 114
)

HANDLER_COUNT = len(HANDLERS)
