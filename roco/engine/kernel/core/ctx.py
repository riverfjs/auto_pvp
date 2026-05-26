"""Reusable stage scratch for the fixed battle kernel."""

from __future__ import annotations

from typing import Any

from roco.common.constants import BPS

_DEFAULTS: tuple[tuple[str, int | float | tuple[Any, ...]], ...] = (
    ("actor_side", 0),
    ("actor_slot", 0),
    ("target_side", 0),
    ("target_slot", 0),
    ("skill_id", 0),
    ("skill_slot", -1),
    ("skill_element", 0),
    ("skill_dam_type", 0),
    ("skill_category", 0),
    ("skill_energy", 0),
    ("skill_flags", 0),
    ("actor_primary", 0),
    ("actor_secondary", -1),
    ("actor_bloodline", -1),
    ("actor_energy", 0),
    ("actor_cute", 0),
    ("actor_hp_lost_quarters", 0),
    ("actor_counter_count", 0),
    ("side_skill_counts", 0),
    ("side_same_skill_count", 0),
    ("side_counter_count", 0),
    ("side_status_skill_count", 0),
    ("side_defense_skill_count", 0),
    ("side_skill_dam_type_counts", 0),
    ("enemy_skill_dam_type_counts", 0),
    ("enemy_switch_count", 0),
    ("side_element_counts", 0),
    ("side_equipped_skill_counts", 0),
    ("side_fainted_count", 0),
    ("side_bench_cute", 0),
    ("side_bug_count", 0),
    ("target_primary", 0),
    ("target_secondary", -1),
    ("target_bloodline", -1),
    ("target_energy", 0),
    ("target_skill_slot", -1),
    ("target_skill_energy", 0),
    ("target_meteor_mark_stacks", 0),
    ("target_positive_buff_layers", 0),
    ("target_poison_stacks", 0),
    ("target_poison_effect_stacks", 0),
    ("power", 0),
    ("hit_count", 1),
    ("power_bps", BPS),
    ("damage_bps", BPS),
    ("heal_bps", BPS),
    ("flat_damage", 0),
    ("damage_dealt", 0),
    ("super_effective", 0),
    ("damage_reduction_bps", BPS),
    ("cost_delta", 0),
    ("enemy_cost_delta", 0),
    ("enemy_cost_turns", 0),
    ("enemy_cost_scope", 0),
    ("consume_enemy_marks_heal_bps", 0),
    ("entry_self_damage_bps", 0),
    ("entry_cost_delta", 0),
    ("self_global_cost_delta", 0),
    ("enemy_global_cost_delta", 0),
    ("self_attack_cost_delta", 0),
    ("enemy_attack_cost_delta", 0),
    ("self_element_cost_reduce", 0),
    ("enemy_element_cost_reduce", 0),
    ("self_global_power_delta", 0),
    ("enemy_global_power_delta", 0),
    ("entry_power_bonus", 0),
    ("entry_element_power_flat", 0),
    ("entry_element_power_bps", 0),
    ("entry_element_cost_reduce", 0),
    ("entry_element_poison_stacks", 0),
    ("entry_element_damage_reduce", 0),
    ("entry_element_damage_resist", 0),
    ("clear_self_element_damage_reduce", 0),
    ("clear_enemy_element_damage_reduce", 0),
    ("mirror_enemy_buffs", 0),
    ("heal_hp_bps", 0),
    ("drain_bps", 0),
    ("heal_energy", 0),
    ("steal_energy", 0),
    ("enemy_lose_energy", 0),
    ("hp_for_energy", 0),
    ("self_buff", 0),
    ("enemy_buff", 0),
    ("self_active_buff_id", 0),
    ("self_active_buff_duration", 0),
    ("enemy_active_buff_id", 0),
    ("enemy_active_buff_duration", 0),
    ("force_switch", 0),
    ("force_enemy_switch", 0),
    ("self_switch_lock_turns", 0),
    ("enemy_switch_lock_turns", 0),
    ("priority_next", 0),
    ("swap_mods", 0),
    ("swap_moves", 0),
    ("exchange_hp_ratio", 0),
    ("actor_hit_delta", 0),
    ("enemy_hit_delta", 0),
    ("enemy_anti_heal", 0),
    ("debuff_extra_layers", 0),
    ("form_transform", 0),
    ("form_transform_heal", 0),
    ("counter_damage", 0),
    ("enemy_cooldown_turns", 0),
    # Set by ``op_set_self_cooldown`` (pak 1037001/1037002 "公共冷却");
    # ``apply_after_move`` writes this many turns into the actor's own
    # cooldown slot for the skill being used.
    ("actor_self_cooldown_turns", 0),
    # Set by ``op_install_counter`` (pak 1031xxx "应对！X" counter
    # triggers); pak ``effect_param[0]`` is the 70xxxxx response
    # skill_id.  ``apply_after_move`` writes it into the actor's
    # ``SideState.counter_skill_id`` slot, and ``mechanics`` fires the
    # looked-up counter skill on the next incoming hit then clears the
    # slot (one-shot).
    ("actor_counter_install_skill_id", 0),
    ("cleanse_self", 0),
    ("cleanse_enemy", 0),
    ("clear_self_buffs", 0),
    ("clear_enemy_buffs", 0),
    ("clear_self_debuffs", 0),
    ("clear_enemy_debuffs", 0),
    ("cute_self", 0),
    ("cute_enemy", 0),
    ("cute_transfer", 0),
    ("interrupt", 0),
    ("counter_category", 0),
    ("counter_success", 0),
    ("first_strike", 0),
    ("burn_stacks", 0),
    ("poison_stacks", 0),
    ("freeze_stacks", 0),
    ("leech_stacks", 0),
    # Snapshot of ``state.marks_dispelled`` from before this stage ran —
    # populated by the residual phase before calling ``run_skill_timing``
    # so handlers like ``op_dispel_marks_to_burn`` can scale their effect
    # by how many marks were just removed this turn.
    ("marks_dispelled", 0),
    ("weather", 0),
    ("weather_turns", 0),
    ("mark_self", 0),
    ("mark_enemy", 0),
    ("clear_self_marks", 0),
    ("clear_enemy_marks", 0),
    ("devotion_random", 0),
    ("cancelled", 0),
    ("pending_actions", ()),
    ("extra_skill_queue", ()),
)

_MOVE_OBSERVATION_FIELDS: tuple[str, ...] = tuple(
    name
    for name, _value in _DEFAULTS[: next(i for i, (field, _value) in enumerate(_DEFAULTS) if field == "power")]
) + (
    "damage_dealt",
    "super_effective",
    "first_strike",
)


class StageCtx:
    __slots__ = tuple(name for name, _ in _DEFAULTS)

    def __init__(self) -> None:
        for name, value in _DEFAULTS:
            object.__setattr__(self, name, value)

    def reset(self, actor_side: int, actor_slot: int, target_side: int, target_slot: int, skill_id: int) -> None:
        for name, value in _DEFAULTS:
            object.__setattr__(self, name, value)
        self.actor_side = actor_side
        self.actor_slot = actor_slot
        self.target_side = target_side
        self.target_slot = target_slot
        self.skill_id = skill_id

    def copy_move_observations_from(self, other: StageCtx) -> None:
        """Copy read-only move observations into a child action context."""
        for name in _MOVE_OBSERVATION_FIELDS:
            object.__setattr__(self, name, getattr(other, name))
