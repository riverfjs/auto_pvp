"""Effect code generation from SKILL_CONF / EFFECT_CONF / BUFF_CONF.

Public surface: :class:`PakTables`, :func:`generate_effect_rows`,
:func:`build_ability_effect_rows`.  Each ``skill_result`` becomes one
``(handler, timing, target, rate, p0-p3)`` row, or an audit gap dict when
the decode resolves to H_NOOP.

Internal layout:

* :mod:`.pak` — lazy pak table loaders
* :mod:`.params` — pak ``effect_param`` extraction + handler-param packing
* :mod:`.classify` — buff_id → handler index, including the tier-scored
  picker for compound effects (marker buff in slot 1, real buff later)
* :mod:`.audit` — gap-reason classification

Timing = ``cast_moment`` directly; Target = ``result_target_type``;
Rate = ``success_rate`` raw (10000 = 100%).
"""

from __future__ import annotations

# Re-export every handler index so callers (and tests) can write
# ``from roco.compiler.effect_codegen import H_BURN`` without reaching into
# ``roco.generated.handler_indices`` directly.
from roco.generated.handler_indices import *  # noqa: F401,F403
from roco.generated.handler_indices import H_NOOP

from roco.compiler.effect_codegen.audit import gap_reason, resolve_buff_metadata
from roco.compiler.effect_codegen.classify import decode_buff_direct, decode_effect
from roco.compiler.effect_codegen.pak import PakTables

__all__ = [
    "PakTables",
    "generate_effect_rows",
    "build_ability_effect_rows",
]


def generate_effect_rows(
    skill_row: dict,
    pak_data: PakTables,
) -> tuple[list[tuple[int, ...]], list[dict]]:
    """Decode a skill's ``skill_result`` into executable rows + audit gaps.

    Returns
    -------
    rows : list[tuple]
        Each tuple is ``(handler_idx, timing, target, rate, p0, p1, p2, p3)``.
    gaps : list[dict]
        One dict per ``skill_result`` entry that resolved to H_NOOP.  Carries
        the original effect_id, resolved buff metadata, and a reason tag so
        downstream tooling can audit unimplemented pak semantics instead of
        silently discarding them.
    """
    rows: list[tuple[int, ...]] = []
    gaps: list[dict] = []

    for entry in skill_row.get("skill_result") or []:
        effect_id = entry.get("effect_id", 0)
        cast_moment = entry.get("cast_moment", 11)
        target_type = entry.get("result_target_type", 1)
        success_rate = entry.get("success_rate", 10000)

        if effect_id in pak_data.effect_conf:
            decoded = decode_effect(effect_id, pak_data.effect_conf, pak_data.buff_conf)
        elif effect_id in pak_data.buff_conf:
            decoded = decode_buff_direct(effect_id, pak_data.buff_conf)
        else:
            decoded = [(H_NOOP, effect_id, 0, 0, 0)]

        for handler_idx, p0, p1, p2, p3 in decoded:
            if handler_idx != H_NOOP:
                rows.append((handler_idx, cast_moment, target_type, success_rate, p0, p1, p2, p3))
                continue
            buff_id, base_ids = resolve_buff_metadata(effect_id, pak_data)
            reason, primitive = gap_reason(effect_id, buff_id, base_ids, pak_data)
            prefixes = sorted({bid // 1000 for bid in base_ids if bid})
            gaps.append({
                "primitive": primitive,
                "timing_code": cast_moment,
                "reason": reason,
                "params": {
                    "effect_id": effect_id,
                    "buff_id": buff_id,
                    "buff_base_ids": list(base_ids),
                    "prefixes": prefixes,
                    "target_type": target_type,
                    "success_rate": success_rate,
                },
            })

    return rows, gaps


def build_ability_effect_rows(
    ability_row: dict,
    pak_data: PakTables,
) -> tuple[list[tuple[int, ...]], list[dict]]:
    """Same as :func:`generate_effect_rows` but tolerates the ``effect_list`` alias."""
    if "skill_result" not in ability_row and "effect_list" in ability_row:
        ability_row = dict(ability_row)
        ability_row["skill_result"] = ability_row["effect_list"]
    return generate_effect_rows(ability_row, pak_data)
