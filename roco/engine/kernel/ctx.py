"""Reusable stage scratch for the fixed battle kernel."""

from __future__ import annotations

BPS = 10000


class StageCtx:
    __slots__ = (
        "actor_side",
        "actor_slot",
        "target_side",
        "target_slot",
        "skill_id",
        "power",
        "hit_count",
        "power_bps",
        "damage_bps",
        "heal_bps",
        "flat_damage",
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
        "cancelled",
    )

    def __init__(self) -> None:
        self.actor_side = 0
        self.actor_slot = 0
        self.target_side = 0
        self.target_slot = 0
        self.skill_id = 0
        self.power = 0
        self.hit_count = 1
        self.power_bps = BPS
        self.damage_bps = BPS
        self.heal_bps = BPS
        self.flat_damage = 0
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
        self.cancelled = 0

    def reset(self, actor_side: int, actor_slot: int, target_side: int, target_slot: int, skill_id: int) -> None:
        self.actor_side = actor_side
        self.actor_slot = actor_slot
        self.target_side = target_side
        self.target_slot = target_slot
        self.skill_id = skill_id
        self.power = 0
        self.hit_count = 1
        self.power_bps = BPS
        self.damage_bps = BPS
        self.heal_bps = BPS
        self.flat_damage = 0
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
        self.cancelled = 0
