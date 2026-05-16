"""Skill effect parser — extracts structured data from free-text Chinese effect descriptions.

Example input: "造成物伤，吸血50%，应对状态：本次技能威力翻倍"
Extracted: life_drain=0.5, counter_status_power_mult=2.0
"""

from __future__ import annotations

import re
from roco.engine.state import SkillRef

# ── Pattern registry ───────────────────────────────────────────

_PATTERNS: list[tuple[re.Pattern, str, str]] = [
    # (regex, field_name, value_type)
    (re.compile(r"吸血\s*(\d+)%"), "life_drain", "pct"),
    (re.compile(r"回复\s*(\d+)%\s*HP"), "self_heal_hp", "pct"),
    (re.compile(r"回复\s*(\d+)%\s*生命"), "self_heal_hp", "pct"),
    (re.compile(r"回复\s*(\d+)\s*能量"), "self_heal_energy", "int"),
    (re.compile(r"偷取\s*(\d+)\s*能量"), "steal_energy", "int"),
    (re.compile(r"敌方失去\s*(\d+)\s*能量"), "enemy_lose_energy", "int"),
    (re.compile(r"减伤\s*(\d+)%"), "damage_reduction", "pct"),
    (re.compile(r"连击\s*(\d+)\s*次"), "hit_count", "int"),
    (re.compile(r"先制\s*\+?(-?\d+)"), "priority_mod", "int"),
    (re.compile(r"优先度\s*\+?(-?\d+)"), "priority_mod", "int"),
    (re.compile(r"折返"), "force_switch", "bool"),
    (re.compile(r"强制换人"), "force_switch", "bool"),
    (re.compile(r"寄生\s*(\d+)\s*层"), "leech_stacks", "int"),
    (re.compile(r"星陨\s*(\d+)\s*层"), "meteor_stacks", "int"),
    (re.compile(r"(\d+)\s*层\s*灼烧"), "burn_stacks", "int"),
    (re.compile(r"(\d+)\s*层\s*中毒"), "poison_stacks", "int"),
    (re.compile(r"(\d+)\s*层\s*冻结"), "freeze_stacks", "int"),
    # Stat changes — self
    (re.compile(r"物攻\s*\+(\d+)%"), "self_atk", "pct"),
    (re.compile(r"物攻\s*\-(\d+)%"), "self_atk", "neg_pct"),
    (re.compile(r"魔攻\s*\+(\d+)%"), "self_spatk", "pct"),
    (re.compile(r"魔攻\s*\-(\d+)%"), "self_spatk", "neg_pct"),
    (re.compile(r"物防\s*\+(\d+)%"), "self_def", "pct"),
    (re.compile(r"物防\s*\-(\d+)%"), "self_def", "neg_pct"),
    (re.compile(r"魔防\s*\+(\d+)%"), "self_spdef", "pct"),
    (re.compile(r"魔防\s*\-(\d+)%"), "self_spdef", "neg_pct"),
    (re.compile(r"速度\s*\+(\d+)%"), "self_speed", "pct"),
    (re.compile(r"速度\s*\-(\d+)%"), "self_speed", "neg_pct"),
    # Stat changes — enemy
    (re.compile(r"敌方物攻\s*\-(\d+)%"), "enemy_atk", "pct"),
    (re.compile(r"敌方魔攻\s*\-(\d+)%"), "enemy_spatk", "pct"),
    (re.compile(r"敌方物防\s*\-(\d+)%"), "enemy_def", "pct"),
    (re.compile(r"敌方魔防\s*\-(\d+)%"), "enemy_spdef", "pct"),
    (re.compile(r"敌方速度\s*\-(\d+)%"), "enemy_speed", "pct"),
]

BURN_KEYWORDS = {"灼烧", "烧伤", "燃烧"}
POISON_KEYWORDS = {"中毒", "剧毒"}
FREEZE_KEYWORDS = {"冻结", "冰冻"}


def parse_effect_text(effect: str) -> dict:
    """Parse a skill's effect text into structured fields."""
    result: dict = {}

    for pattern, field, vtype in _PATTERNS:
        m = pattern.search(effect)
        if not m:
            continue

        if vtype == "bool":
            result[field] = True
        elif vtype == "int":
            result[field] = int(m.group(1))
        elif vtype == "pct":
            result[field] = int(m.group(1)) / 100.0
        elif vtype == "neg_pct":
            result[field] = -int(m.group(1)) / 100.0

    # Keyword-based status detection (if not caught by regex)
    if "burn_stacks" not in result:
        for kw in BURN_KEYWORDS:
            if kw in effect:
                result["burn_stacks"] = result.get("burn_stacks", 1)
    if "poison_stacks" not in result:
        for kw in POISON_KEYWORDS:
            if kw in effect:
                result["poison_stacks"] = result.get("poison_stacks", 1)
    if "freeze_stacks" not in result:
        for kw in FREEZE_KEYWORDS:
            if kw in effect:
                result["freeze_stacks"] = result.get("freeze_stacks", 1)

    return result


def apply_effects_to_skill(skill: SkillRef) -> SkillRef:
    """Parse effect text and populate SkillRef fields. Returns the same object."""
    if not skill.effect:
        return skill
    parsed = parse_effect_text(skill.effect)
    for field, value in parsed.items():
        if hasattr(skill, field):
            setattr(skill, field, value)
    return skill
