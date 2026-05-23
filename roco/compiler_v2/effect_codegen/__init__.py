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

# Re-export every handler index so callers (and tests) can write
# ``from roco.compiler_v2.effect_codegen import H_BURN`` without reaching into
# ``roco.generated.handler_indices`` directly.
from roco.generated.handler_indices import *  # noqa: F401,F403

from roco.compiler_v2.effect_codegen.classify import decode_buff_direct, decode_effect
from roco.compiler_v2.effect_codegen.exact_decoders import decode_exact
from roco.compiler_v2.effect_codegen.family_axes import decode_family_axes
from roco.compiler_v2.effect_codegen.outcomes import (
    AbilityFlagOutcome,
    EmitOutcome,
    GapOutcome,
)
from roco.compiler_v2.effect_codegen.pak import PakTables
from roco.compiler_v2.effect_codegen.params import is_status_or_mark_handler

__all__ = [
    "PakTables",
    "generate_effect_rows",
    "build_ability_effect_rows",
]


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

        # Pak-axis family decoders win first — they read pak's own
        # schema fields (e.g. ``effect_order``) so the whole family is
        # covered uniformly without per-id rule rows.  Same return
        # shape as ``decode_exact`` so the tuple/timing handling below
        # serves both.
        family = decode_family_axes(
            effect_id, pak_data.effect_conf, pak_data.buff_conf,
        )
        if family is not None:
            if isinstance(family, tuple):
                outcome, timing_override = family
                timing = timing_override or cast_moment
            else:
                outcome = family
                timing = cast_moment
            rows.append(_emit_row(
                outcome,
                timing=timing,
                target_type=target_type,
                success_rate=success_rate,
                buff_group_level=buff_group_level,
            ))
            continue

        # Hand-curated exact decoders (currently generated weather setters)
        # take precedence over the structural decoder.
        override = decode_exact(effect_id)
        if override is not None:
            if isinstance(override, tuple):
                outcome, timing_override = override
                timing = timing_override or cast_moment
            else:
                outcome = override
                timing = cast_moment
            rows.append(_emit_row(
                outcome,
                timing=timing,
                target_type=target_type,
                success_rate=success_rate,
                buff_group_level=buff_group_level,
            ))
            continue

        if effect_id in pak_data.effect_conf:
            outcomes = decode_effect(effect_id, pak_data.effect_conf, pak_data.buff_conf)
        elif effect_id in pak_data.buff_conf:
            outcomes = decode_buff_direct(effect_id, pak_data.buff_conf)
        else:
            outcomes = [GapOutcome(
                primitive=f"effect_{effect_id}",
                effect_id=effect_id,
                buff_id=None,
                reason="effect_id_not_in_pak",
                params={"effect_id": effect_id},
            )]

        for outcome in outcomes:
            if isinstance(outcome, EmitOutcome):
                rows.append(_emit_row(
                    outcome,
                    timing=cast_moment,
                    target_type=target_type,
                    success_rate=success_rate,
                    buff_group_level=buff_group_level,
                ))
            elif isinstance(outcome, GapOutcome):
                gaps.append(_gap_dict(outcome, cast_moment, order, target_type, success_rate))
            elif isinstance(outcome, AbilityFlagOutcome):
                if not allow_ability_flags:
                    raise RuntimeError(
                        f"AbilityFlagOutcome leaked into a non-ability decoding "
                        f"path (effect_id={outcome.effect_id}, "
                        f"flag={outcome.flag_name}). generate_effect_rows must "
                        f"be called with allow_ability_flags=True only from "
                        f"ability builders."
                    )
                # The bit is set later by compiler_v2.ability_flags via the
                # ability_effect_ids × pak-derived ability flag join.
                continue
            else:
                raise RuntimeError(f"unknown effect decoder outcome: {outcome!r}")

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
