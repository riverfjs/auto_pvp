"""Effect primitive generation from SKILL_CONF / EFFECT_CONF / BUFF_CONF.

Public surface: :class:`PakTables`, :func:`generate_effect_rows`,
:func:`build_ability_effect_rows`.  The compiler emits pak reference rows;
the engine later links those references to kernel handlers.

Outcome routing:

* :class:`EmitOutcome` → effect_rows (primitive row).
* :class:`GapOutcome` → generated audit/debug gap metadata.

Internal layout:

* :mod:`.outcomes` — row/gap dataclasses
* :mod:`.pak` — lazy pak table loaders
* :mod:`.params` — pak ``effect_param`` extraction helpers
* :mod:`.classify` — pak ref emission and source-level gap outcomes
* :mod:`.audit` — gap-row metadata helper (no longer classifies)

Timing = ``battle_event:<Enum.BattleEvent symbol>`` from ``cast_moment``;
Target = ``result_target_type``;
Rate = ``success_rate`` raw (10000 = 100%).
"""

from __future__ import annotations

from roco.compiler_v2.effect_codegen.classify import (
    decode_buff_direct,
    decode_effect,
)
from roco.common.primitive_keys import BUFF_REF_PREFIX
from roco.compiler_v2.effect_codegen.outcomes import (
    EmitOutcome,
    GapOutcome,
)
from roco.compiler_v2.effect_codegen.pak import PakTables
from roco.compiler_v2.timing_keys import pak_cast_moment_key

__all__ = [
    "PakTables",
    "generate_effect_rows",
    "build_ability_effect_rows",
]


def _emit_row(
    outcome: EmitOutcome,
    *,
    timing: str,
    target_type: int,
    success_rate: int,
    buff_group_level: int,
) -> tuple[object, ...]:
    """Pack a pak reference outcome plus per-entry pak fields."""
    p0, p1, p2, p3 = outcome.p0, outcome.p1, outcome.p2, outcome.p3
    if outcome.primitive.startswith(BUFF_REF_PREFIX):
        p0 = int(buff_group_level or 0)
    return (
        outcome.primitive,
        timing,
        target_type,
        success_rate,
        p0,
        p1,
        p2,
        p3,
    )


def _decode_reference_outcomes(
    ref_id: int,
    pak_data: PakTables,
    source_row: dict | None,
) -> list[tuple[EmitOutcome | GapOutcome, str | None]]:
    if ref_id in pak_data.effect_conf:
        outcomes = decode_effect(ref_id, pak_data.effect_conf, pak_data.buff_conf)
    elif ref_id in pak_data.buff_conf:
        outcomes = decode_buff_direct(ref_id, pak_data.buff_conf)
    else:
        outcomes = [GapOutcome(
            primitive=f"effect_{ref_id}",
            effect_id=ref_id,
            buff_id=None,
            reason="effect_id_not_in_pak",
            params={"effect_id": ref_id},
        )]
    return [(outcome, None) for outcome in outcomes]


def _decode_reference_rows(
    ref_id: int,
    pak_data: PakTables,
    *,
    timing: str,
    target_type: int,
    success_rate: int,
    buff_group_level: int,
    effect_order: int,
    source_row: dict | None,
    visited: frozenset[int] = frozenset(),
) -> tuple[list[tuple[object, ...]], list[dict]]:
    if ref_id in visited:
        gap = GapOutcome(
            primitive=f"effect_{ref_id}",
            effect_id=ref_id if ref_id in pak_data.effect_conf else None,
            buff_id=ref_id if ref_id in pak_data.buff_conf else None,
            reason="assign_recursive_ref",
            params={"effect_id": ref_id if ref_id in pak_data.effect_conf else None, "buff_id": ref_id if ref_id in pak_data.buff_conf else None},
        )
        return [], [_gap_dict(gap, timing, effect_order, target_type, success_rate)]
    next_visited = visited | {ref_id}

    rows: list[tuple[object, ...]] = []
    gaps: list[dict] = []
    for outcome, timing_override in _decode_reference_outcomes(ref_id, pak_data, source_row):
        row_timing = timing_override or timing
        if isinstance(outcome, EmitOutcome):
            rows.append(_emit_row(
                outcome,
                timing=row_timing,
                target_type=target_type,
                success_rate=success_rate,
                buff_group_level=buff_group_level,
            ))
        elif isinstance(outcome, GapOutcome):
            gaps.append(_gap_dict(outcome, row_timing, effect_order, target_type, success_rate))
        else:
            raise RuntimeError(f"unknown effect decoder outcome: {outcome!r}")
    return rows, gaps


def generate_effect_rows(
    skill_row: dict,
    pak_data: PakTables,
) -> tuple[list[tuple[object, ...]], list[dict]]:
    """Decode a ``skill_result`` list into (rows, gaps).

    Parameters
    ----------
    skill_row, pak_data
        Standard inputs from the skill / ability builder.
    Returns
    -------
    rows : list[tuple]
        Each tuple is ``(primitive, timing, target, rate, p0, p1, p2, p3)``.
        The compiler never emits engine handler indices.
    gaps : list[dict]
        Unsupported / unrecognised effects for generated audit output.

    Raises
    ------
    RuntimeError
        For malformed source rows only.
    """
    rows: list[tuple[object, ...]] = []
    gaps: list[dict] = []

    for order, entry in enumerate(skill_row.get("skill_result") or []):
        effect_id = entry.get("effect_id", 0)
        if not effect_id:
            # Pak pads ``skill_result`` with bare ``{}`` placeholders between
            # real effects.  These carry no semantics and would otherwise
            # flood ``effect_gaps`` with ``effect_0`` noise.
            continue
        if "cast_moment" not in entry:
            gap = GapOutcome(
                primitive=f"effect_{int(effect_id)}",
                effect_id=int(effect_id),
                buff_id=int(effect_id) if int(effect_id) in pak_data.buff_conf else None,
                reason="skill_result_missing_cast_moment",
                params={"effect_id": int(effect_id), "skill_result_index": order},
            )
            gaps.append(_gap_dict(gap, "", order, entry.get("result_target_type", 1), entry.get("success_rate", 10000)))
            continue
        cast_moment = pak_cast_moment_key(int(entry.get("cast_moment") or 0))
        target_type = entry.get("result_target_type", 1)
        success_rate = entry.get("success_rate", 10000)
        buff_group_level = int(entry.get("buff_group_level", 0) or 0)

        child_rows, child_gaps = _decode_reference_rows(
            int(effect_id),
            pak_data,
            timing=cast_moment,
            target_type=target_type,
            success_rate=success_rate,
            buff_group_level=buff_group_level,
            effect_order=order,
            source_row=skill_row,
        )
        rows.extend(child_rows)
        gaps.extend(child_gaps)

    return rows, gaps


def build_ability_effect_rows(
    ability_row: dict,
    pak_data: PakTables,
) -> tuple[list[tuple[object, ...]], list[dict]]:
    """Decode an ability's effect rows; tolerates the ``effect_list`` alias."""
    if "skill_result" not in ability_row and "effect_list" in ability_row:
        ability_row = dict(ability_row)
        ability_row["skill_result"] = ability_row["effect_list"]
    return generate_effect_rows(ability_row, pak_data)


def _gap_dict(
    gap: GapOutcome,
    timing_code: object,
    effect_order: int,
    target_type: int,
    success_rate: int,
) -> dict:
    """Serialise a :class:`GapOutcome` into the legacy gap-row dict shape."""
    params = dict(gap.params)
    params.setdefault("effect_id", gap.effect_id)
    params.setdefault("buff_id", gap.buff_id)
    params.setdefault("target_type", target_type)
    params.setdefault("success_rate", success_rate)
    return {
        "primitive": gap.primitive,
        "timing_code": timing_code,
        "effect_order": effect_order,
        "reason": gap.reason,
        "params": params,
    }
