"""BWiki skill text classifier for canonical skill rows."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from roco.compiler.classifiers.common import (
    ClassificationResult,
    ManualRules,
    apply_manual,
    category,
    int_value,
    load_manual_rules,
    missing_gaps,
)
from roco.compiler.classifiers.marks import generated_mark_effects
from roco.compiler.effect_compile import compile_skill_effects
from roco.compiler.records import SkillData
from roco.compiler.skill_tags import classify
from roco.engine.enums import normalize_element_name


def classify_skill_record(
    record: Mapping[str, Any],
    manual_rules: ManualRules | None = None,
) -> ClassificationResult:
    """Classify one canonical skill record into canonical effect rows."""
    manual_rules = manual_rules if manual_rules is not None else load_manual_rules("skill")
    skill = SkillData(
        name=str(record.get("name", "")),
        element=normalize_element_name(str(record.get("element", "普通"))),
        category=category(record.get("category", "物攻")),
        energy=int_value(record.get("energy"), 0),
        power=int_value(record.get("power"), 0),
        effect=str(record.get("effect_text", "")),
    )
    classify(skill)
    generated = tuple(_skill_effect_to_record(row) for row in compile_skill_effects(0, skill))
    generated = generated + generated_mark_effects(skill.effect)
    effects, source = apply_manual("skill", skill.name, generated, manual_rules)
    gaps = missing_gaps("skill", skill.name, skill.effect, effects)
    return ClassificationResult(int(skill.effect_flags), tuple(effects), gaps, source)


def refresh_skill_classification(
    record: Mapping[str, Any],
    manual_rules: ManualRules | None = None,
) -> dict[str, Any]:
    result = classify_skill_record(record, manual_rules)
    updated = dict(record)
    updated["flags"] = result.flags
    updated["effects"] = list(result.effects)
    updated["classification"] = result.meta()
    return updated


def _skill_effect_to_record(row) -> dict[str, Any]:
    return {
        "timing": row.effect.timing.name,
        "tag": row.effect.tag.name,
        "params": dict(row.effect.params),
        "condition": row.effect.condition,
        "sort_order": row.sort_order,
    }
