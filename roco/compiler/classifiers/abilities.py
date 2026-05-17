"""BWiki ability description classifier for canonical ability rows."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from roco.compiler.classifiers.ability_rules import generated_ability_effects
from roco.compiler.classifiers.common import (
    ClassificationResult,
    ManualRules,
    apply_manual,
    load_manual_rules,
    missing_gaps,
)


def classify_ability_record(
    record: Mapping[str, Any],
    manual_rules: ManualRules | None = None,
) -> ClassificationResult:
    """Classify one canonical ability record into canonical effect rows."""
    manual_rules = manual_rules if manual_rules is not None else load_manual_rules("ability")
    name = str(record.get("name", "")).strip()
    desc = str(record.get("description", "")).strip()
    generated = generated_ability_effects(desc)
    effects, source = apply_manual("ability", name, generated, manual_rules)
    gaps = missing_gaps("ability", name, desc, effects)
    return ClassificationResult(0, tuple(effects), gaps, source)


def refresh_ability_classification(
    record: Mapping[str, Any],
    manual_rules: ManualRules | None = None,
) -> dict[str, Any]:
    result = classify_ability_record(record, manual_rules)
    updated = dict(record)
    updated["flags"] = result.flags
    updated["effects"] = list(result.effects)
    updated["classification"] = result.meta()
    return updated
