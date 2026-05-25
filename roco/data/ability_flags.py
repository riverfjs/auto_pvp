"""Populate ``ABILITY_FLAGS`` from ability ``skill_result`` provenance."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from roco.common.enums import AbilityFlag
from roco.data.ability_flags_from_effects import (
    load_ability_flags_from_effects,
    normalized_payload as _rules_normalized_payload,
)
from roco.data.ability_flag_rules import AbilityFlagRule


def load_effect_flag_table() -> dict[int, AbilityFlagRule]:
    """Load the ability-flag semantic table using default pak paths."""

    return load_ability_flags_from_effects()


def populate(
    ability_effect_ids: Iterable[tuple[int, int, int, int, int, int, int] | Mapping[str, Any]],
    *,
    effect_to_flag: dict[int, AbilityFlagRule],
    ability_flags: list[int],
) -> int:
    """OR matched flag bits into ``ability_flags`` in place."""

    if not effect_to_flag:
        return 0
    matched = 0
    capacity = len(ability_flags)
    for row in ability_effect_ids:
        if isinstance(row, Mapping):
            ability_id = int(row["ability_id"])
            effect_id = int(row["effect_id"])
        else:
            ability_id = int(row[0])
            effect_id = int(row[2])
        outcome = effect_to_flag.get(int(effect_id))
        if outcome is None:
            continue
        if not (0 <= ability_id < capacity):
            raise RuntimeError(
                f"ability_effect_ids row references ability_id={ability_id} "
                f"outside of compiled range [0, {capacity})"
            )
        ability_flags[ability_id] |= int(AbilityFlag[outcome.flag_name])
        matched += 1
    return matched


def normalized_payload(
    effect_to_flag: dict[int, AbilityFlagRule] | None = None,
) -> tuple[tuple[int, str], ...]:
    """Stable ``(skill_result.effect_id, flag_name)`` tuple for source hashing."""

    table = effect_to_flag if effect_to_flag is not None else load_effect_flag_table()
    return _rules_normalized_payload(table)
