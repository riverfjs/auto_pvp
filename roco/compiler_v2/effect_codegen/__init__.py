"""Effect code generation from SKILL_CONF / EFFECT_CONF / BUFF_CONF.

Public surface: :class:`PakTables`, :func:`generate_effect_rows`,
:func:`build_ability_effect_rows`.  Each ``skill_result`` entry resolves
to exactly one :class:`EmitOutcome`, :class:`GapOutcome`, or
:class:`AbilityFlagOutcome` — never the H_NOOP
sentinel.  ``H_NOOP`` itself only exists at the kernel dispatch layer
(``ops.py``) as the "skip this row" index.

Outcome routing:

* :class:`EmitOutcome` → effect_rows (runtime kernel row).
* :class:`GapOutcome` → ``effect_gaps`` table (blocks strict ``build_db``).
* :class:`AbilityFlagOutcome` → dropped here; later compiled into the
  catalog ``ABILITY_FLAGS`` tuple by
  :mod:`roco.compiler_v2.ability_flags` via the join of
  the ``ability_effect_ids`` table × pak-derived ability flag semantics.
  Only :func:`build_ability_effect_rows` accepts this outcome — the
  generic ``generate_effect_rows`` rejects it unless explicitly opted
  in via ``allow_ability_flags=True``, so a stray ability-passive
  effect_id never silently applies to a per-cast skill row.

Internal layout:

* :mod:`.outcomes` — row/gap/ability-flag dataclasses
* :mod:`.pak` — lazy pak table loaders
* :mod:`.params` — pak ``effect_param`` extraction + handler-param packing
* :mod:`.classify` — buff_id → handler index; structural + gap outcomes;
  also consults :mod:`.ability_flags_from_effects` to surface
  :class:`AbilityFlagOutcome` for pak-derived passive ability rows.
* :mod:`.exact_decoders` — generated exact tables, currently weather
* :mod:`.ability_flags_from_effects` — pak effect_id → AbilityFlag bit
  rules loader (effects that compile to passive flags, not runtime rows)
* :mod:`.audit` — gap-row metadata helper (no longer classifies)

Timing = ``cast_moment`` directly; Target = ``result_target_type``;
Rate = ``success_rate`` raw (10000 = 100%).
"""

from __future__ import annotations

from dataclasses import dataclass

# Re-export every handler index so callers (and tests) can write
# ``from roco.compiler_v2.effect_codegen import H_BURN`` without reaching into
# ``roco.generated.handler_indices`` directly.
from roco.generated.handler_indices import *  # noqa: F401,F403

from roco.compiler_v2.effect_codegen.classify import (
    collect_buff_candidates,
    decode_buff_direct,
    decode_effect,
)
from roco.compiler_v2.effect_codegen.exact_decoders import decode_exact
from roco.compiler_v2.effect_codegen.family_axes import decode_family_axes
from roco.compiler_v2.effect_codegen.outcomes import (
    AbilityFlagOutcome,
    EmitOutcome,
    GapOutcome,
)
from roco.compiler_v2.effect_codegen.pak import PakTables
from roco.compiler_v2.effect_codegen.params import is_status_or_mark_handler
from roco.compiler_v2.effect_codegen.source_context import decode_source_context
from roco.generated.buffbase_params import BUFFBASE_ORDER, BUFFBASE_PARAMS

__all__ = [
    "PakTables",
    "generate_effect_rows",
    "build_ability_effect_rows",
]


BFT_ASSIGN_ORDER = 17


@dataclass(frozen=True)
class _AssignRef:
    ref_id: int
    target_type: int | None
    success_rate: int
    source_buff_id: int
    source_base_id: int


def _as_int_tuple(value: object) -> tuple[int, ...]:
    if isinstance(value, tuple):
        raw_values = value
    elif isinstance(value, list):
        raw_values = tuple(value)
    elif value is None:
        raw_values = ()
    else:
        raw_values = (value,)
    out: list[int] = []
    for raw in raw_values:
        try:
            item = int(raw)
        except (TypeError, ValueError):
            continue
        if item:
            out.append(item)
    return tuple(out)


def _emit_row(
    outcome: EmitOutcome,
    *,
    timing: int,
    target_type: int,
    success_rate: int,
    buff_group_level: int,
) -> tuple[int, ...]:
    """Pack an :class:`EmitOutcome` plus per-entry pak fields into a runtime row.

    Stack-count priority: pak's own ``effect_param`` shape (``stacks`` —
    buff_id repeats, e.g. 焚烧烙印 packs 5 burn copies to mean 5 stacks)
    wins because pak is the source of truth.  Only when pak does not
    encode a count at the param level do we fall back to the
    skill_result's ``buff_group_level`` (e.g. 剧毒 says
    ``buff_group_level=3`` and stores a direct buff reference with no
    repeats).
    """
    p0, p1, p2, p3 = outcome.p0, outcome.p1, outcome.p2, outcome.p3
    if outcome.stacks > 1:
        stacks = outcome.stacks
    elif buff_group_level > 0:
        stacks = buff_group_level
    else:
        stacks = 1
    if is_status_or_mark_handler(outcome.handler_idx) and stacks > 1:
        p0 = stacks
    elif outcome.handler_idx == H_HIT_COUNT_DELTA and stacks > 1:
        p0 *= stacks
    assert outcome.handler_idx > 0, (
        "EmitOutcome must carry a non-zero handler_idx; "
        f"got {outcome.handler_idx}"
    )
    return (
        outcome.handler_idx,
        timing,
        target_type,
        success_rate,
        p0,
        p1,
        p2,
        p3,
    )


def _assign_refs(
    buff_id: int,
    pak_data: PakTables,
) -> tuple[list[_AssignRef], list[GapOutcome]] | None:
    rec = pak_data.buff_conf.get(buff_id)
    if rec is None:
        return None
    base_ids = [int(v) for v in rec.get("buff_base_ids") or () if v]
    assign_base_ids = [
        base_id for base_id in base_ids
        if BUFFBASE_ORDER.get(base_id) == BFT_ASSIGN_ORDER
    ]
    if not assign_base_ids:
        return None
    refs: list[_AssignRef] = []
    gaps: list[GapOutcome] = []
    for base_id in assign_base_ids:
        params = BUFFBASE_PARAMS.get(base_id) or ()
        raw_refs = _as_int_tuple(params[0] if len(params) > 0 else ())
        rate = int(params[1]) if len(params) > 1 and not isinstance(params[1], tuple) else 10000
        target_code = int(params[2]) if len(params) > 2 and not isinstance(params[2], tuple) else 0
        if not raw_refs:
            gaps.append(GapOutcome(
                primitive=f"assign_{base_id}",
                effect_id=None,
                buff_id=buff_id,
                reason="assign_no_refs",
                params={"buff_id": buff_id, "buff_base_id": base_id},
            ))
            continue
        if rate <= 0:
            gaps.append(GapOutcome(
                primitive=f"assign_{base_id}",
                effect_id=None,
                buff_id=buff_id,
                reason="assign_zero_rate",
                params={"buff_id": buff_id, "buff_base_id": base_id, "rate": rate},
            ))
            continue
        if target_code not in (0, 1, 2, 3, 4):
            gaps.append(GapOutcome(
                primitive=f"assign_condition_{target_code}",
                effect_id=None,
                buff_id=buff_id,
                reason="assign_condition_unsupported",
                params={
                    "buff_id": buff_id,
                    "buff_base_id": base_id,
                    "assigned_refs": list(raw_refs),
                    "assign_target_or_condition": target_code,
                },
            ))
            continue
        for ref_id in raw_refs:
            refs.append(_AssignRef(
                ref_id=ref_id,
                target_type=target_code or None,
                success_rate=rate,
                source_buff_id=buff_id,
                source_base_id=base_id,
            ))
    return refs, gaps


def _single_assign_buff_from_effect(
    effect_id: int,
    pak_data: PakTables,
) -> int:
    rec = pak_data.effect_conf.get(effect_id)
    if rec is None or int(rec.get("type", 0) or 0) != 1:
        return 0
    params_raw = rec.get("effect_param") or rec.get("params") or []
    candidates = collect_buff_candidates(params_raw, pak_data.buff_conf)
    if len(candidates) != 1:
        return 0
    buff_id = candidates[0]
    return buff_id if _assign_refs(buff_id, pak_data) is not None else 0


def _decode_reference_outcomes(
    ref_id: int,
    pak_data: PakTables,
    source_row: dict | None,
) -> list[tuple[EmitOutcome | GapOutcome | AbilityFlagOutcome, int | None]]:
    family = decode_family_axes(ref_id, pak_data.effect_conf, pak_data.buff_conf)
    if family is not None:
        if isinstance(family, tuple):
            outcome, timing_override = family
            return [(outcome, timing_override)]
        return [(family, None)]

    override = decode_exact(ref_id)
    if override is not None:
        if isinstance(override, tuple):
            outcome, timing_override = override
            return [(outcome, timing_override)]
        return [(override, None)]

    source_outcomes = decode_source_context(ref_id, pak_data, source_row)
    if source_outcomes is not None:
        return source_outcomes

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
    timing: int,
    target_type: int,
    success_rate: int,
    buff_group_level: int,
    effect_order: int,
    allow_ability_flags: bool,
    root_ref_id: int,
    source_row: dict | None,
    visited: frozenset[int] = frozenset(),
) -> tuple[list[tuple[int, ...]], list[dict]]:
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

    assign_buff_id = ref_id if ref_id in pak_data.buff_conf else _single_assign_buff_from_effect(ref_id, pak_data)
    assigned = _assign_refs(assign_buff_id, pak_data) if assign_buff_id else None
    if assigned is not None:
        refs, assign_gaps = assigned
        rows: list[tuple[int, ...]] = []
        gaps: list[dict] = []
        for gap in assign_gaps:
            gap_dict = _gap_dict(gap, timing, effect_order, target_type, success_rate)
            gap_dict["params"].setdefault("assigned_from", ref_id)
            gaps.append(gap_dict)
        for ref in refs:
            child_rows, child_gaps = _decode_reference_rows(
                ref.ref_id,
                pak_data,
                timing=timing,
                target_type=ref.target_type or target_type,
                success_rate=success_rate * ref.success_rate // 10000,
                buff_group_level=1,
                effect_order=effect_order,
                allow_ability_flags=allow_ability_flags,
                root_ref_id=root_ref_id,
                source_row=source_row,
                visited=next_visited,
            )
            rows.extend(child_rows)
            for gap in child_gaps:
                gap["params"].setdefault("assigned_from", ref.source_buff_id)
                gap["params"].setdefault("assigned_from_base", ref.source_base_id)
                gap["params"].setdefault("assigned_ref", ref.ref_id)
                gaps.append(gap)
        return rows, gaps

    rows: list[tuple[int, ...]] = []
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
        elif isinstance(outcome, AbilityFlagOutcome):
            if allow_ability_flags and outcome.effect_id == root_ref_id:
                continue
            gaps.append(_gap_dict(
                GapOutcome(
                    primitive=f"effect_{outcome.effect_id}",
                    effect_id=outcome.effect_id,
                    buff_id=outcome.effect_id if outcome.effect_id in pak_data.buff_conf else None,
                    reason="assign_ability_flag_requires_provenance",
                    params={"effect_id": outcome.effect_id, "flag": outcome.flag_name},
                ),
                row_timing,
                effect_order,
                target_type,
                success_rate,
            ))
        else:
            raise RuntimeError(f"unknown effect decoder outcome: {outcome!r}")
    return rows, gaps


def generate_effect_rows(
    skill_row: dict,
    pak_data: PakTables,
    *,
    allow_ability_flags: bool = False,
) -> tuple[list[tuple[int, ...]], list[dict]]:
    """Decode a ``skill_result`` list into (rows, gaps).

    Parameters
    ----------
    skill_row, pak_data
        Standard inputs from the skill / ability builder.
    allow_ability_flags : bool, default False
        Whether to accept :class:`AbilityFlagOutcome` results from the
        decoder.  Skill builders **must not** set this — ability-passive
        bits applied to a per-cast skill row would corrupt the
        runtime contract.  Ability builders set this to True via
        :func:`build_ability_effect_rows`; the outcome is then dropped
        from rows / gaps and the bit is set later by
        :mod:`roco.compiler_v2.ability_flags`.

    Returns
    -------
    rows : list[tuple]
        Each tuple is ``(handler_idx, timing, target, rate, p0, p1, p2, p3)``.
        ``handler_idx`` is always > 0 (H_NOOP is forbidden at this layer).
    gaps : list[dict]
        Unsupported / unrecognised effects.  Used + non-zero ``used_count``
        rows block strict ``build_db``.

    Raises
    ------
    RuntimeError
        If a decoder returns :class:`AbilityFlagOutcome` while
        ``allow_ability_flags`` is False — that means a pak ability-flag
        effect_id leaked into a non-ability decoding path.
    """
    rows: list[tuple[int, ...]] = []
    gaps: list[dict] = []

    for order, entry in enumerate(skill_row.get("skill_result") or []):
        effect_id = entry.get("effect_id", 0)
        if not effect_id:
            # Pak pads ``skill_result`` with bare ``{}`` placeholders between
            # real effects.  These carry no semantics and would otherwise
            # flood ``effect_gaps`` with ``effect_0`` noise.
            continue
        cast_moment = entry.get("cast_moment", 11)
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
            allow_ability_flags=allow_ability_flags,
            root_ref_id=int(effect_id),
            source_row=skill_row,
        )
        if not allow_ability_flags:
            leaked = [
                gap for gap in child_gaps
                if gap.get("reason") == "assign_ability_flag_requires_provenance"
            ]
            if leaked:
                first = leaked[0]["params"]
                raise RuntimeError(
                    f"AbilityFlagOutcome leaked into a non-ability decoding "
                    f"path (effect_id={first.get('effect_id')}, "
                    f"flag={first.get('flag')}). generate_effect_rows must "
                    f"be called with allow_ability_flags=True only from "
                    f"ability builders."
                )
        rows.extend(child_rows)
        gaps.extend(child_gaps)

    return rows, gaps


def build_ability_effect_rows(
    ability_row: dict,
    pak_data: PakTables,
) -> tuple[list[tuple[int, ...]], list[dict]]:
    """Decode an ability's effect rows; tolerates the ``effect_list`` alias.

    Unlike a skill builder, this path accepts :class:`AbilityFlagOutcome`
    results (passive bits compiled into ``ABILITY_FLAGS``).  The bit
    itself is populated later by
    :mod:`roco.compiler_v2.ability_flags`; the outcome is
    dropped here.
    """
    if "skill_result" not in ability_row and "effect_list" in ability_row:
        ability_row = dict(ability_row)
        ability_row["skill_result"] = ability_row["effect_list"]
    return generate_effect_rows(ability_row, pak_data, allow_ability_flags=True)


def _gap_dict(
    gap: GapOutcome,
    timing_code: int,
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
