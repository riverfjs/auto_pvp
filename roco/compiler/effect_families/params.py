"""pak ``effect_param`` decoding helpers.

These helpers operate on the raw ``effect_param`` field shape used by both
EFFECT_CONF and BUFF_CONF rows:

* :func:`_vec_from_param_slot` normalizes a single slot (which can be a
  ``{"params": [...]}`` dict, a bare list, or a scalar) into an integer
  tuple.
* :func:`_classify_slot_refs` counts how many integers in a slot reference
  EFFECT_CONF / BUFF_CONF / SKILL_CONF ids vs non-references.
* :func:`_collect_param_shape` aggregates the per-slot view across every
  source id in a family and returns the catalog ``param_shape`` document.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from roco.compiler.effect_codegen.pak import PakTables


def _vec_from_param_slot(slot: Any) -> tuple[int, ...]:
    """pak slot → integer tuple.  Empty / non-list → ``()``."""
    if isinstance(slot, dict):
        inner = slot.get("params")
        if isinstance(inner, list):
            return tuple(int(x) for x in inner if isinstance(x, (int, float)))
    if isinstance(slot, list):
        return tuple(int(x) for x in slot if isinstance(x, (int, float)))
    if isinstance(slot, (int, float)):
        return (int(slot),)
    return ()


def _classify_slot_refs(
    vectors: list[tuple[int, ...]],
    effect_conf: dict[int, dict],
    buff_conf: dict[int, dict],
    skill_conf: dict[int, dict],
) -> dict[str, int]:
    """Per-slot count of how many values reference EFFECT/BUFF/SKILL ids."""
    counts = {
        "effect_ref_count": 0,
        "buff_ref_count": 0,
        "skill_ref_count": 0,
        "non_ref_count": 0,
    }
    for vec in vectors:
        for v in vec:
            if v <= 0:
                counts["non_ref_count"] += 1
            elif v in effect_conf:
                counts["effect_ref_count"] += 1
            elif v in buff_conf:
                counts["buff_ref_count"] += 1
            elif v in skill_conf:
                counts["skill_ref_count"] += 1
            else:
                counts["non_ref_count"] += 1
    return counts


def _collect_param_shape(
    source_ids: list[int],
    record_lookup: dict[int, dict],
    pak: PakTables,
) -> dict:
    """Build the ``param_shape`` sub-document from a family's source rows.

    For each slot index seen across the family's effect_param rows, collect:
    distinct vectors (up to 10), distinct count, sample vectors, and per-slot
    cross-reference counts (effect / buff / skill / non_ref).
    """
    observed_lengths: set[int] = set()
    by_slot: dict[int, list[tuple[int, ...]]] = defaultdict(list)
    for sid in source_ids:
        rec = record_lookup.get(sid)
        if rec is None:
            continue
        params = rec.get("effect_param") or rec.get("params") or []
        observed_lengths.add(len(params))
        for idx, slot in enumerate(params):
            by_slot[idx].append(_vec_from_param_slot(slot))
    slots: list[dict] = []
    for idx in sorted(by_slot):
        vecs = by_slot[idx]
        unique: list[tuple[int, ...]] = []
        for v in vecs:
            if v not in unique:
                unique.append(v)
        unique.sort()
        distinct = len(unique)
        if distinct <= 10:
            observed_vectors = [list(v) for v in unique]
            sample_vectors = observed_vectors
        else:
            observed_vectors = []
            sample_vectors = [list(v) for v in unique[:5]]
        refs = _classify_slot_refs(vecs, pak.effect_conf, pak.buff_conf, pak.skill_conf)
        slots.append({
            "slot": idx,
            "observed_param_vectors": observed_vectors,
            "distinct_vector_count": distinct,
            "sample_vectors": sample_vectors,
            **refs,
        })
    return {
        "observed_lengths": sorted(observed_lengths),
        "slots": slots,
    }
