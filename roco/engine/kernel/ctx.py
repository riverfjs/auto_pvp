"""Reusable stage scratch for the fixed battle kernel."""

from __future__ import annotations

from roco.engine.common.rules import BPS


class StageCtx:
    __slots__ = (
        "actor_side",
        "actor_slot",
        "target_side",
        "target_slot",
        "skill_id",
        "skill_slot",
        "skill_element",
        "skill_category",
        "skill_energy",
        "skill_flags",
        "actor_primary",
        "actor_secondary",
        "actor_bloodline",
        "actor_energy",
        "actor_cute",
        "actor_hp_lost_quarters",
        "actor_counter_count",
        "side_skill_counts",
        "side_counter_count",
        "side_status_skill_count",
        "side_bench_cute",
        "side_bug_count",
        "target_primary",
        "target_secondary",
        "target_bloodline",
        "target_skill_slot",
        "target_skill_energy",
        "target_poison_stacks",
        "power",
        "hit_count",
        "power_bps",
        "damage_bps",
        "heal_bps",
        "flat_damage",
        "damage_dealt",
        "super_effective",
        "damage_reduction_bps",
        "cost_delta",
        "enemy_cost_delta",
        "enemy_cost_turns",
        "enemy_cost_scope",
        "consume_enemy_marks_heal_bps",
        "entry_self_damage_bps",
        "entry_cost_delta",
        "entry_power_bonus",
        "mirror_enemy_buffs",
        "heal_hp_bps",
        "drain_bps",
        "heal_energy",
        "steal_energy",
        "enemy_lose_energy",
        "hp_for_energy",
        "self_buff",
        "enemy_buff",
        "force_switch",
        "force_enemy_switch",
        "priority_next",
        "swap_mods",
        "swap_moves",
        "exchange_hp_ratio",
        "enemy_hit_delta",
        "enemy_anti_heal",
        "debuff_extra_layers",
        "form_transform",
        "form_transform_heal",
        "counter_damage",
        "enemy_cooldown_turns",
        "cleanse_self",
        "cleanse_enemy",
        "clear_self_buffs",
        "clear_enemy_buffs",
        "clear_self_debuffs",
        "clear_enemy_debuffs",
        "cute_self",
        "cute_enemy",
        "cute_transfer",
        "interrupt",
        "counter_category",
        "counter_success",
        "first_strike",
        "burn_stacks",
        "poison_stacks",
        "freeze_stacks",
        "leech_stacks",
        "weather",
        "weather_turns",
        "mark_self",
        "mark_enemy",
        "clear_self_marks",
        "clear_enemy_marks",
        "devotion_random",
        "cancelled",
    )

    def __init__(self) -> None:
        self.actor_side = 0
        self.actor_slot = 0
        self.target_side = 0
        self.target_slot = 0
        self.skill_id = 0
        self.skill_slot = -1
        self.skill_element = 0
        self.skill_category = 0
        self.skill_energy = 0
        self.skill_flags = 0
        self.actor_primary = 0
        self.actor_secondary = -1
        self.actor_bloodline = -1
        self.actor_energy = 0
        self.actor_cute = 0
        self.actor_hp_lost_quarters = 0
        self.actor_counter_count = 0
        self.side_skill_counts = 0
        self.side_counter_count = 0
        self.side_status_skill_count = 0
        self.side_bench_cute = 0
        self.side_bug_count = 0
        self.target_primary = 0
        self.target_secondary = -1
        self.target_bloodline = -1
        self.target_skill_slot = -1
        self.target_skill_energy = 0
        self.target_poison_stacks = 0
        self.power = 0
        self.hit_count = 1
        self.power_bps = BPS
        self.damage_bps = BPS
        self.heal_bps = BPS
        self.flat_damage = 0
        self.damage_dealt = 0
        self.super_effective = 0
        self.damage_reduction_bps = BPS
        self.cost_delta = 0
        self.enemy_cost_delta = 0
        self.enemy_cost_turns = 0
        self.enemy_cost_scope = 0
        self.consume_enemy_marks_heal_bps = 0
        self.entry_self_damage_bps = 0
        self.entry_cost_delta = 0
        self.entry_power_bonus = 0
        self.mirror_enemy_buffs = 0
        self.heal_hp_bps = 0
        self.drain_bps = 0
        self.heal_energy = 0
        self.steal_energy = 0
        self.enemy_lose_energy = 0
        self.hp_for_energy = 0
        self.self_buff = 0
        self.enemy_buff = 0
        self.force_switch = 0
        self.force_enemy_switch = 0
        self.priority_next = 0
        self.swap_mods = 0
        self.swap_moves = 0
        self.exchange_hp_ratio = 0
        self.enemy_hit_delta = 0
        self.enemy_anti_heal = 0
        self.debuff_extra_layers = 0
        self.form_transform = 0
        self.form_transform_heal = 0
        self.counter_damage = 0
        self.enemy_cooldown_turns = 0
        self.cleanse_self = 0
        self.cleanse_enemy = 0
        self.clear_self_buffs = 0
        self.clear_enemy_buffs = 0
        self.clear_self_debuffs = 0
        self.clear_enemy_debuffs = 0
        self.cute_self = 0
        self.cute_enemy = 0
        self.cute_transfer = 0
        self.interrupt = 0
        self.counter_category = 0
        self.counter_success = 0
        self.first_strike = 0
        self.burn_stacks = 0
        self.poison_stacks = 0
        self.freeze_stacks = 0
        self.leech_stacks = 0
        self.weather = 0
        self.weather_turns = 0
        self.mark_self = 0
        self.mark_enemy = 0
        self.clear_self_marks = 0
        self.clear_enemy_marks = 0
        self.devotion_random = 0
        self.cancelled = 0

    def reset(self, actor_side: int, actor_slot: int, target_side: int, target_slot: int, skill_id: int) -> None:
        self.actor_side = actor_side
        self.actor_slot = actor_slot
        self.target_side = target_side
        self.target_slot = target_slot
        self.skill_id = skill_id
        self.skill_slot = -1
        self.skill_element = 0
        self.skill_category = 0
        self.skill_energy = 0
        self.skill_flags = 0
        self.actor_primary = 0
        self.actor_secondary = -1
        self.actor_bloodline = -1
        self.actor_energy = 0
        self.actor_cute = 0
        self.actor_hp_lost_quarters = 0
        self.actor_counter_count = 0
        self.side_skill_counts = 0
        self.side_counter_count = 0
        self.side_status_skill_count = 0
        self.side_bench_cute = 0
        self.side_bug_count = 0
        self.target_primary = 0
        self.target_secondary = -1
        self.target_bloodline = -1
        self.target_skill_slot = -1
        self.target_skill_energy = 0
        self.target_poison_stacks = 0
        self.power = 0
        self.hit_count = 1
        self.power_bps = BPS
        self.damage_bps = BPS
        self.heal_bps = BPS
        self.flat_damage = 0
        self.damage_dealt = 0
        self.super_effective = 0
        self.damage_reduction_bps = BPS
        self.cost_delta = 0
        self.enemy_cost_delta = 0
        self.enemy_cost_turns = 0
        self.enemy_cost_scope = 0
        self.consume_enemy_marks_heal_bps = 0
        self.entry_self_damage_bps = 0
        self.entry_cost_delta = 0
        self.entry_power_bonus = 0
        self.mirror_enemy_buffs = 0
        self.heal_hp_bps = 0
        self.drain_bps = 0
        self.heal_energy = 0
        self.steal_energy = 0
        self.enemy_lose_energy = 0
        self.hp_for_energy = 0
        self.self_buff = 0
        self.enemy_buff = 0
        self.force_switch = 0
        self.force_enemy_switch = 0
        self.priority_next = 0
        self.swap_mods = 0
        self.swap_moves = 0
        self.exchange_hp_ratio = 0
        self.enemy_hit_delta = 0
        self.enemy_anti_heal = 0
        self.debuff_extra_layers = 0
        self.form_transform = 0
        self.form_transform_heal = 0
        self.counter_damage = 0
        self.enemy_cooldown_turns = 0
        self.cleanse_self = 0
        self.cleanse_enemy = 0
        self.clear_self_buffs = 0
        self.clear_enemy_buffs = 0
        self.clear_self_debuffs = 0
        self.clear_enemy_debuffs = 0
        self.cute_self = 0
        self.cute_enemy = 0
        self.cute_transfer = 0
        self.interrupt = 0
        self.counter_category = 0
        self.counter_success = 0
        self.first_strike = 0
        self.burn_stacks = 0
        self.poison_stacks = 0
        self.freeze_stacks = 0
        self.leech_stacks = 0
        self.weather = 0
        self.weather_turns = 0
        self.mark_self = 0
        self.mark_enemy = 0
        self.clear_self_marks = 0
        self.clear_enemy_marks = 0
        self.devotion_random = 0
        self.cancelled = 0
