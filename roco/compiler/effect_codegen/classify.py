"""Pak-effect classification — pak-first, no H_NOOP at the boundary.

Each decoder returns ``list[EmitOutcome | GapOutcome | AbilityFlagOutcome]``
(never H_NOOP tuples).  See :mod:`.outcomes` for the four-state contract.

Dispatch for ``EFFECT_CONF`` rows (see :func:`decode_effect`):

* ``type=2`` decodes structurally from ``effect_param`` to ``H_DAMAGE``.
* ``type=1`` whose ``effect_param`` contains exactly one buff_id in
  BUFF_CONF is treated as "apply that buff"; the buff is then classified
  via :func:`classify_buff_handler` (exact ``buff_base_id`` → prefix
  family fallback).  Single-candidate effects are deterministic — pak
  literally wrote one buff to apply.
* ``type=1`` with multiple buff_ids and any ``type=3`` row require
  human-verified semantics: see :mod:`.exact_decoders` (runtime row) and
  :mod:`.ability_flags_from_effects` (ability passive flag).  Anything
  not covered surfaces as a :class:`GapOutcome` rather than being
  heuristically guessed.

  ``type=3`` rows that match an entry in ``ability_flags_from_effects.jsonl``
  surface as :class:`AbilityFlagOutcome` — the bit is compiled into
  ``ABILITY_FLAGS`` rather than into a runtime row.  Only the ability
  builder path accepts that outcome; the skill builder raises if it
  ever sees one (see :func:`generate_effect_rows`).

``classify_buff_handler`` (exact ``buff_base_id`` then prefix) is also
used by :func:`decode_buff_direct` when a skill_result references a
buff in BUFF_CONF directly — that path has no ambiguity since the entry
*is* the buff to apply.
"""

from __future__ import annotations

import json
from pathlib import Path

from roco.generated.handler_indices import H_DAMAGE

from roco.compiler.effect_codegen.outcomes import AbilityFlagOutcome, EmitOutcome, GapOutcome
from roco.compiler.effect_codegen.params import (
    extract_int_list,
    pack_handler_params,
    safe_int,
)


def _load_ability_flag_table() -> dict[int, AbilityFlagOutcome]:
    """Load the effect → AbilityFlagOutcome map; empty on first-run boot.

    Imported lazily inside the function so module import doesn't trigger
    a full pak read at collect time (the loader pulls ``EFFECT_CONF.json``
    when no override is supplied).
    """
    from roco.compiler.effect_codegen.ability_flags_from_effects import (
        load_ability_flags_from_effects,
    )
    rules_path = Path(__file__).resolve().parents[2] / "compiler" / "rules" / "ability_flags_from_effects.jsonl"
    if not rules_path.exists():
        return {}
    return load_ability_flags_from_effects(rules_path=rules_path)


ABILITY_FLAG_OUTCOMES: dict[int, AbilityFlagOutcome] = _load_ability_flag_table()


def count_buff_repeats(params_raw: list, buff_id: int) -> int:
    """Count how many times ``buff_id`` appears in any single ``effect_param`` slot.

    Pak encodes status stack count by repeating the buff_id in the same slot
    (e.g. 1042014's ``effect_param[2] = [20070020]*5`` means 5 burn stacks).
    Returns 1 when ``buff_id`` is absent or only appears once.
    """
    if not buff_id:
        return 1
    for idx in range(len(params_raw)):
        n = extract_int_list(params_raw, idx).count(buff_id)
        if n > 1:
            return n
    return 1


_MAP_PATH = Path(__file__).resolve().parents[2] / "generated" / "prefix_handler_map.json"


def _load_handler_maps() -> tuple[dict[int, int], dict[int, int]]:
    if not _MAP_PATH.exists():
        return {}, {}
    data = json.loads(_MAP_PATH.read_text(encoding="utf-8"))
    prefix_map = {int(k): v for k, v in data.get("prefix_map", {}).items()}
    base_id_map = {int(k): v for k, v in data.get("base_id_map", {}).items()}
    return prefix_map, base_id_map


PREFIX_HANDLER_MAP, BASE_ID_HANDLER_MAP = _load_handler_maps()


def classify_buff_handler(buff_id: int, buff_conf: dict[int, dict]) -> int:
    """Map a buff_id to a handler index via exact-base-id then prefix lookup.

    Returns 0 when no mapping exists; callers must convert 0 into a
    :class:`GapOutcome` rather than emitting a runtime row.
    """
    rec = buff_conf.get(buff_id)
    if rec is None:
        return 0
    base_ids = rec.get("buff_base_ids") or []
    for bid in base_ids:
        if bid and bid in BASE_ID_HANDLER_MAP:
            return BASE_ID_HANDLER_MAP[bid]
    for bid in base_ids:
        if bid:
            h = PREFIX_HANDLER_MAP.get(bid // 1000, 0)
            if h:
                return h
    return 0


def collect_buff_candidates(
    params_raw: list,
    buff_conf: dict[int, dict],
) -> list[int]:
    """Return every distinct buff_id referenced by an ``effect_param`` payload.

    Used by :mod:`.audit` to attach metadata to gap rows; not used by
    classification (the structural decoder requires exactly one candidate,
    the exact-decoder table covers everything else).
    """
    seen: list[int] = []
    for idx in range(len(params_raw)):
        for v in extract_int_list(params_raw, idx):
            if v in buff_conf and v not in seen:
                seen.append(v)
    return seen


def _single_buff(params_raw: list, buff_conf: dict[int, dict]) -> int:
    """If ``params_raw`` references exactly one BUFF_CONF id, return it; else 0."""
    candidates = collect_buff_candidates(params_raw, buff_conf)
    return candidates[0] if len(candidates) == 1 else 0


def _buff_gap(effect_id: int | None, buff_id: int, buff_conf: dict[int, dict]) -> GapOutcome:
    """Build a GapOutcome for a buff classification miss.

    ``classify_buff_handler`` returned 0 — figure out *why* and pick a
    precise reason so the audit row points at the actual coverage hole
    (missing base_id mapping, intentional-noop-removed prefix, unseeded
    prefix, or empty buff record).
    """
    rec = buff_conf.get(buff_id)
    if rec is None:
        return GapOutcome(
            primitive=f"buff_{buff_id}",
            effect_id=effect_id,
            buff_id=buff_id,
            reason="buff_not_in_pak",
            params={"effect_id": effect_id, "buff_id": buff_id},
        )
    base_ids = [int(b) for b in (rec.get("buff_base_ids") or []) if b]
    if not base_ids:
        return GapOutcome(
            primitive=f"buff_{buff_id}",
            effect_id=effect_id,
            buff_id=buff_id,
            reason="buff_no_base_ids",
            params={"effect_id": effect_id, "buff_id": buff_id, "buff_base_ids": []},
        )
    # base_id present but neither exact nor prefix matched.  Report the
    # first unmapped prefix as the primitive.  "Unmapped" means either
    # the prefix is absent from PREFIX_HANDLER_MAP or it is present with
    # a zero handler (defensive — the generator no longer emits zeros,
    # but treat both shapes the same so a stale prefix_handler_map.json
    # can't silently shadow gaps as ``buff_unclassified``).
    for bid in base_ids:
        pfx = bid // 1000
        if bid in BASE_ID_HANDLER_MAP:
            continue
        if PREFIX_HANDLER_MAP.get(pfx, 0) == 0:
            return GapOutcome(
                primitive=f"prefix_{pfx}",
                effect_id=effect_id,
                buff_id=buff_id,
                reason=f"prefix_{pfx}_unmapped",
                params={
                    "effect_id": effect_id,
                    "buff_id": buff_id,
                    "buff_base_ids": base_ids,
                    "prefixes": sorted({b // 1000 for b in base_ids}),
                },
            )
    # Every base_id has a mapped prefix but pack_handler_params (or some
    # caller) still rejected — keep a precise fall-through.
    return GapOutcome(
        primitive=f"buff_{buff_id}",
        effect_id=effect_id,
        buff_id=buff_id,
        reason="buff_unclassified",
        params={
            "effect_id": effect_id,
            "buff_id": buff_id,
            "buff_base_ids": base_ids,
            "prefixes": sorted({b // 1000 for b in base_ids}),
        },
    )


def decode_effect(
    effect_id: int,
    effect_conf: dict[int, dict],
    buff_conf: dict[int, dict],
) -> list[EmitOutcome | GapOutcome | AbilityFlagOutcome]:
    """Decode one ``EFFECT_CONF`` row into outcomes.

    Returns at least one outcome.  ``type=1`` no-buff, compound, and every
    ``type=3`` row default to :class:`GapOutcome`; the structural ``type=1``
    single-buff path and ``type=2`` damage produce :class:`EmitOutcome`;
    rows listed in ``ability_flags_from_effects.jsonl`` produce
    :class:`AbilityFlagOutcome` (only the ability builder accepts that —
    the skill builder rejects it loudly).
    """
    flag_outcome = ABILITY_FLAG_OUTCOMES.get(effect_id)
    if flag_outcome is not None:
        return [flag_outcome]
    rec = effect_conf.get(effect_id)
    if rec is None:
        return [GapOutcome(
            primitive=f"effect_{effect_id}",
            effect_id=effect_id,
            buff_id=None,
            reason="effect_id_not_in_pak",
            params={"effect_id": effect_id},
        )]

    etype = rec.get("type", 0)
    params_raw = rec.get("effect_param") or rec.get("params") or []

    if etype == 1:
        candidates = collect_buff_candidates(params_raw, buff_conf)
        if len(candidates) == 1:
            buff_id = candidates[0]
            h = classify_buff_handler(buff_id, buff_conf)
            if h:
                raw_stacks = count_buff_repeats(params_raw, buff_id)
                p0, p1, p2, p3 = pack_handler_params(h, buff_id, buff_conf, raw_stacks)
                return [EmitOutcome(h, p0, p1, p2, p3, raw_stacks)]
            return [_buff_gap(effect_id, buff_id, buff_conf)]
        if len(candidates) > 1:
            return [GapOutcome(
                primitive=f"effect_{effect_id}",
                effect_id=effect_id,
                buff_id=candidates[0],  # first candidate for metadata only
                reason="effect_type_1_compound",
                params={
                    "effect_id": effect_id,
                    "buff_candidates": candidates,
                },
            )]
        return [GapOutcome(
            primitive=f"effect_{effect_id}",
            effect_id=effect_id,
            buff_id=None,
            reason="effect_type_1_no_buff",
            params={
                "effect_id": effect_id,
                "param_head": [safe_int(params_raw, 0), safe_int(params_raw, 1)],
            },
        )]

    if etype == 2:
        mode = safe_int(params_raw, 0)
        power = safe_int(params_raw, 2)
        self_damage = safe_int(params_raw, 6)
        return [EmitOutcome(H_DAMAGE, mode, power, self_damage, 0, 1)]

    if etype == 3:
        return [GapOutcome(
            primitive=f"effect_{effect_id}",
            effect_id=effect_id,
            buff_id=None,
            reason="effect_type_3_state_change",
            params={"effect_id": effect_id},
        )]

    return [GapOutcome(
        primitive=f"effect_{effect_id}",
        effect_id=effect_id,
        buff_id=None,
        reason=f"effect_type_{etype}_unknown",
        params={"effect_id": effect_id, "type": etype},
    )]


def decode_buff_direct(
    buff_id: int,
    buff_conf: dict[int, dict],
) -> list[EmitOutcome | GapOutcome]:
    """Decode a direct ``BUFF_CONF`` reference (not via ``EFFECT_CONF``).

    No ``effect_param`` to inspect, so ``raw_stacks`` defaults to 1; the
    caller supplies ``buff_group_level`` from the skill_result entry.
    """
    h = classify_buff_handler(buff_id, buff_conf)
    if h:
        p0, p1, p2, p3 = pack_handler_params(h, buff_id, buff_conf)
        return [EmitOutcome(h, p0, p1, p2, p3, 1)]
    return [_buff_gap(None, buff_id, buff_conf)]
