"""Coverage bucketing + family-key derivation.

Routes a single pak ``source_id`` through the decoder stack and reports
which coverage bucket it falls in, derives the per-family
``coverage_status`` label from the bucket histogram, and maps a
direct-BUFF_CONF reference to its family_key (reusing the gap-primitive's
``base_ids[0] // 1000`` rule, not ``buff_id // 1000``).
"""

from __future__ import annotations

from roco.compiler_v2.effect_codegen.assign import assign_refs, single_assign_buff_from_effect
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
from roco.compiler_v2.effect_codegen.source_context import decode_source_context


COVERAGE_STATUSES = frozenset({
    "auto_structural",
    "exact_semantic",
    "exact_semantic_partial",
    "generated_weather",
    "gap",
    "ability_flag",
    "ability_flag_partial",
    "mixed",
})


def _classify_one_source_id(
    sid: int,
    *,
    pak: PakTables,
    weather_ids: set[int],
    exact_emit_ids: set[int],
    ability_flag_ids: frozenset[int],
    source_rows: list[dict] | None = None,
) -> str:
    """Run the actual decoder path and report which bucket ``sid`` falls in.

    Order matters: weather / exact semantics / ability_flag win
    before structural decode.  ``ability_flag_ids`` is consulted *before*
    :func:`decode_effect` so the bucket is stable regardless of the
    decode call's consumer-context (decode_effect's AbilityFlagOutcome
    branch only fires when the rules file is present, which is also true
    here, but the explicit check makes the family-audit semantics
    deterministic).
    """
    if sid in weather_ids:
        return "generated_weather"
    if sid in exact_emit_ids:
        return "exact_semantic"
    if sid in ability_flag_ids:
        return "ability_flag"
    assign_bucket = _classify_assign_source_id(sid, pak)
    if assign_bucket is not None:
        return assign_bucket
    # Defensive: decode_exact may still return something (e.g. compound),
    # though the two id sets above are derived from the same JSONL.
    override = decode_exact(sid)
    if override is not None:
        return "exact_semantic"
    if sid in pak.effect_conf:
        # Pak-axis family decoders (effect_order family etc.) — pak-native
        # so they win over the type-based structural fallback.  Bucket the
        # result as ``auto_structural`` since the source is pak's own
        # schema rather than a hand-curated rule.
        family = decode_family_axes(sid, pak.effect_conf, pak.buff_conf)
        if family is not None:
            return "auto_structural"
        context_bucket = _classify_with_source_context(sid, pak, source_rows)
        if context_bucket is not None:
            return context_bucket
        outcomes = decode_effect(sid, pak.effect_conf, pak.buff_conf)
    elif sid in pak.buff_conf:
        context_bucket = _classify_with_source_context(sid, pak, source_rows)
        if context_bucket is not None:
            return context_bucket
        outcomes = decode_buff_direct(sid, pak.buff_conf)
    else:
        return "gap"
    # The earlier ``sid in ability_flag_ids`` short-circuit catches this in
    # the normal path; this fallback guards against any future case where
    # decode_effect emits the outcome but our ``ability_flag_ids`` set
    # diverges from the loader's table (build-time misconfiguration).
    if any(isinstance(o, AbilityFlagOutcome) for o in outcomes):
        return "ability_flag"
    has_emit = any(isinstance(o, EmitOutcome) for o in outcomes)
    has_gap = any(isinstance(o, GapOutcome) for o in outcomes)
    if has_emit and not has_gap:
        return "auto_structural"
    return "gap"


def _classify_assign_source_id(sid: int, pak: PakTables) -> str | None:
    """Classify BFT_ASSIGN rows as pak-structural dispatchers.

    Child refs are audited by their own EFFECT_CONF / BUFF_CONF families; this
    bucket only answers whether the assign dispatcher row itself is understood.
    """
    assign_buff_id = sid if sid in pak.buff_conf else single_assign_buff_from_effect(
        sid,
        pak.effect_conf,
        pak.buff_conf,
        collect_buff_candidates,
    )
    if not assign_buff_id:
        return None
    assigned = assign_refs(assign_buff_id, pak.buff_conf)
    if assigned is None:
        return None
    refs, gaps = assigned
    if gaps or not refs:
        return "gap"
    return "auto_structural"


def _classify_with_source_context(
    sid: int,
    pak: PakTables,
    source_rows: list[dict] | None,
) -> str | None:
    if not source_rows:
        return None
    buckets: list[str] = []
    for source_row in source_rows:
        outcomes = decode_source_context(sid, pak, source_row)
        if outcomes is None:
            continue
        decoded = [outcome for outcome, _timing in outcomes]
        has_emit = any(isinstance(outcome, EmitOutcome) for outcome in decoded)
        has_gap = any(isinstance(outcome, GapOutcome) for outcome in decoded)
        buckets.append("gap" if has_gap or not has_emit else "auto_structural")
    if not buckets:
        return None
    return "gap" if "gap" in buckets else "auto_structural"


def _derive_coverage_status(breakdown: dict[str, int]) -> str:
    nonzero = {k: v for k, v in breakdown.items() if v > 0}
    if not nonzero:
        return "gap"
    if len(nonzero) == 1:
        only = next(iter(nonzero))
        return {
            "auto_structural_count": "auto_structural",
            "exact_semantic_count": "exact_semantic",
            "generated_weather_count": "generated_weather",
            "gap_count": "gap",
            "ability_flag_count": "ability_flag",
        }[only]
    if set(nonzero) == {"exact_semantic_count", "gap_count"}:
        return "exact_semantic_partial"
    if set(nonzero) == {"ability_flag_count", "gap_count"}:
        return "ability_flag_partial"
    if "ability_flag_count" in nonzero and "exact_semantic_count" in nonzero:
        # Belt-and-suspenders against the cross-check that already runs in
        # build_families(): a family that's both runtime-row and
        # ability-flag has incompatible semantics.  Surface as "mixed" so
        # the audit explicitly flags it even if the cross-check were
        # somehow disabled.
        return "mixed"
    return "mixed"


def _buff_family_key(buff_id: int, buff_conf: dict[int, dict]) -> tuple[str, int | None]:
    """Map a direct BUFF_CONF id to (family_key, base_id_prefix).

    Reuses the gap-primitive logic from :func:`classify._buff_gap`: first
    non-zero ``buff_base_id`` divided by 1000 — *not* ``buff_id // 1000``.
    """
    rec = buff_conf.get(buff_id)
    if rec is None:
        return f"buff_conf_direct:buff_{buff_id}", None
    base_ids = [int(b) for b in (rec.get("buff_base_ids") or []) if b]
    if not base_ids:
        return "buff_conf_direct:buff_no_base_ids", None
    prefix = base_ids[0] // 1000
    return f"buff_conf_direct:prefix_{prefix}", prefix
