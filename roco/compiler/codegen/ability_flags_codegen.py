"""Populate ``ABILITY_FLAGS`` from ``ability_effect_ids`` × rules JSONL.

This is the fourth-outcome counterpart to the runtime effect-row codegen:
where :func:`generate_effect_rows` writes runtime rows for EmitOutcomes,
this module writes passive bits into the per-ability ``ABILITY_FLAGS``
tuple.  No runtime kernel code is involved — the bits are then read by
``state._pet_state`` via ``hot.ABILITY_FLAGS[ability_id]``.

Data flow:

1. :func:`load_effect_flag_table` — loads the strict
   ``ability_flags_from_effects.jsonl`` rules.  Returns
   ``effect_id → AbilityFlagOutcome``.
2. :func:`populate` — runs a single SQL join against the
   ``ability_effect_ids`` table (no canonical-jsonl reads) and OR's the
   matched bit into ``ability_flags[ability_id]`` in place.
3. :func:`normalized_payload` re-exports the rules table in sorted
   tuple form so ``_source_payload()`` can hash it.
"""

from __future__ import annotations

import sqlite3

from roco.common.enums import AbilityFlag
from roco.compiler.effect_codegen.ability_flags_from_effects import (
    load_ability_flags_from_effects,
    normalized_payload as _rules_normalized_payload,
)
from roco.compiler.effect_codegen.outcomes import AbilityFlagOutcome


def load_effect_flag_table() -> dict[int, AbilityFlagOutcome]:
    """Load the rules table from disk, using all-default paths."""
    return load_ability_flags_from_effects()


def populate(
    conn: sqlite3.Connection,
    *,
    effect_to_flag: dict[int, AbilityFlagOutcome],
    ability_flags: list[int],
) -> int:
    """OR matched flag bits into ``ability_flags`` (in place).

    Reads ``ability_effect_ids`` (ability_id, effect_id pairs only — pak
    provenance fields are unused here) and, for every effect_id that has
    a matching :class:`AbilityFlagOutcome`, OR's its bit into the
    ability's slot.  ``ability_flags`` is the same list owned by
    ``artifact._compile_artifacts``; modifying it in place mirrors the
    legacy zero-fill behaviour the function used to perform.

    Returns the number of (ability_id, effect_id) pairs that contributed
    a non-zero bit.  Useful for sanity assertions in tests / build output.
    """
    if not effect_to_flag:
        return 0
    matched = 0
    rows = conn.execute(
        "SELECT ability_id, effect_id FROM ability_effect_ids ORDER BY ability_id, sort_order"
    )
    capacity = len(ability_flags)
    for ability_id, effect_id in rows:
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
    effect_to_flag: dict[int, AbilityFlagOutcome] | None = None,
) -> tuple[tuple[int, str], ...]:
    """Stable ``(effect_id, flag_name)`` tuple for ``_source_payload``.

    Used so any change to the rules JSONL surfaces as a SOURCE_HASH
    change downstream (the table contents directly determine which bits
    end up in ``ABILITY_FLAGS``).
    """
    table = effect_to_flag if effect_to_flag is not None else load_effect_flag_table()
    return _rules_normalized_payload(table)
