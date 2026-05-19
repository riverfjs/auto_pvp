"""Pak-effect classification — pak-first, no heuristics.

Dispatch for ``EFFECT_CONF`` rows (see :func:`decode_effect`):

* ``type=2`` decodes structurally from ``effect_param`` to ``H_DAMAGE``.
* ``type=1`` whose ``effect_param`` contains exactly one buff_id in
  BUFF_CONF is treated as "apply that buff"; the buff is then classified
  via :func:`classify_buff_handler` (exact ``buff_base_id`` → prefix
  family fallback).  Single-candidate effects are deterministic — pak
  literally wrote one buff to apply.
* ``type=1`` with multiple buff_ids in ``effect_param`` and any ``type=3``
  state-change row require human-verified semantics: see
  :mod:`.exact_decoders`.  Anything not in that table surfaces as an
  audit gap rather than being heuristically guessed.

``classify_buff_handler`` (exact ``buff_base_id`` then prefix) is also
used by :func:`decode_buff_direct` when a skill_result references a
buff in BUFF_CONF directly — that path has no ambiguity since the entry
*is* the buff to apply.
"""

from __future__ import annotations

import json
from pathlib import Path

from roco.generated.handler_indices import H_DAMAGE, H_NOOP

from roco.compiler.effect_codegen.params import (
    extract_int_list,
    pack_handler_params,
    safe_int,
)




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
    """Map a buff_id to a handler index via exact-base-id then prefix lookup."""
    rec = buff_conf.get(buff_id)
    if rec is None:
        return H_NOOP
    base_ids = rec.get("buff_base_ids") or []
    for bid in base_ids:
        if bid and bid in BASE_ID_HANDLER_MAP:
            return BASE_ID_HANDLER_MAP[bid]
    for bid in base_ids:
        if bid:
            h = PREFIX_HANDLER_MAP.get(bid // 1000, H_NOOP)
            if h != H_NOOP:
                return h
    return H_NOOP


def collect_buff_candidates(
    params_raw: list,
    buff_conf: dict[int, dict],
) -> list[int]:
    """Return every distinct buff_id referenced by an ``effect_param`` payload.

    Used by :mod:`.audit` to report which buffs a dropped effect referenced;
    not used by classification (the structural decoder requires exactly one
    candidate, the exact-decoder table covers everything else).
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


def decode_effect(
    effect_id: int,
    effect_conf: dict[int, dict],
    buff_conf: dict[int, dict],
) -> list[tuple[int, int, int, int, int, int]]:
    """Decode one ``EFFECT_CONF`` row into ``(handler, p0..p3, raw_stacks)`` tuples.

    Multi-candidate ``type=1`` effects and every ``type=3`` row must be
    listed in :mod:`.exact_decoders` to produce an executable row; this
    function intentionally returns H_NOOP for them so the audit pipeline
    surfaces the coverage gap rather than guessing.
    """
    rec = effect_conf.get(effect_id)
    if rec is None:
        return [(H_NOOP, effect_id, 0, 0, 0, 1)]

    etype = rec.get("type", 0)
    params_raw = rec.get("effect_param") or rec.get("params") or []

    if etype == 1:
        buff_id = _single_buff(params_raw, buff_conf)
        if buff_id:
            h = classify_buff_handler(buff_id, buff_conf)
            raw_stacks = count_buff_repeats(params_raw, buff_id)
            p0, p1, p2, p3 = pack_handler_params(h, buff_id, buff_conf, raw_stacks)
            return [(h, p0, p1, p2, p3, raw_stacks)]
        return [(H_NOOP, safe_int(params_raw, 0), safe_int(params_raw, 1), 0, 0, 1)]

    if etype == 2:
        mode = safe_int(params_raw, 0)
        power = safe_int(params_raw, 2)
        self_damage = safe_int(params_raw, 6)
        return [(H_DAMAGE, mode, power, self_damage, 0, 1)]

    if etype == 3:
        # All state-change rows must be in exact_decoders; default → gap.
        return [(H_NOOP, effect_id, 0, 0, 0, 1)]

    return [(H_NOOP, effect_id, etype, 0, 0, 1)]


def decode_buff_direct(
    buff_id: int,
    buff_conf: dict[int, dict],
) -> list[tuple[int, int, int, int, int, int]]:
    """Decode a direct ``BUFF_CONF`` reference (not via ``EFFECT_CONF``).

    No ``effect_param`` to inspect, so ``raw_stacks`` defaults to 1; the
    caller supplies ``buff_group_level`` from the skill_result entry.
    """
    h = classify_buff_handler(buff_id, buff_conf)
    p0, p1, p2, p3 = pack_handler_params(h, buff_id, buff_conf)
    return [(h, p0, p1, p2, p3, 1)]
