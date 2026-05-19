"""Pak-effect classification: buff_id → kernel handler index.

Two layers:

1. ``classify_buff_handler`` — given a single buff_id, look up its
   ``buff_base_ids`` in ``base_id_map`` (exact match) and then
   ``prefix_map`` (family by ``base_id // 1000``).
2. ``pick_effect_buff`` — given an ``EFFECT_CONF.effect_param`` payload
   that may contain *multiple* buff_ids (compound effects like
   "convert mark to burn", where slot 1 is a tracking marker and later
   slots hold the buff to actually apply), choose the buff_id whose
   classification is the most specific.

Both maps are loaded once from ``prefix_handler_map.json`` (regenerated
by ``gen_prefix_map.py``) so adding mappings is a codegen change, not a
code change.
"""

from __future__ import annotations

import json
from pathlib import Path

from roco.generated.handler_indices import H_DAMAGE, H_NOOP, H_SELF_BUFF

from roco.compiler.effect_codegen.params import (
    extract_int_list,
    pack_handler_params,
    safe_int,
)


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

    Order follows the slot order in pak; duplicates are removed but slot
    ordering is preserved so consumers that want first-found semantics can
    still take ``candidates[0]``.
    """
    seen: list[int] = []
    for idx in range(len(params_raw)):
        for v in extract_int_list(params_raw, idx):
            if v in buff_conf and v not in seen:
                seen.append(v)
    return seen


def pick_effect_buff(
    candidates: list[int],
    buff_conf: dict[int, dict],
) -> int:
    """Choose the most semantically-specific buff_id among ``candidates``.

    Compound pak effects (e.g. ``effect_id`` 1042014 "标记转换灼烧") put a
    tracking marker buff in slot 1 and the actually-applied buff in slot 2.
    A naive "first non-zero" selector picks the marker (prefix 2001 STAT_MOD
    → H_SELF_BUFF) and the burn is silently lost.

    Tier order:

    1. ``buff_base_id`` has an exact entry in :data:`BASE_ID_HANDLER_MAP`
       (covers H_BURN/H_POISON/H_LEECH/marks — handlers configured by
       :func:`gen_prefix_map.py` because their semantics are unambiguous).
    2. prefix maps to a handler that is neither H_NOOP nor the generic
       H_SELF_BUFF catch-all.
    3. prefix maps to H_SELF_BUFF.
    4. fall back to first candidate.
    """
    if not candidates:
        return 0

    def base_ids(c: int) -> list[int]:
        return [bid for bid in (buff_conf[c].get("buff_base_ids") or []) if bid]

    for c in candidates:
        if any(bid in BASE_ID_HANDLER_MAP for bid in base_ids(c)):
            return c
    for c in candidates:
        for bid in base_ids(c):
            h = PREFIX_HANDLER_MAP.get(bid // 1000, H_NOOP)
            if h not in (H_NOOP, H_SELF_BUFF):
                return c
    for c in candidates:
        for bid in base_ids(c):
            if PREFIX_HANDLER_MAP.get(bid // 1000, H_NOOP) == H_SELF_BUFF:
                return c
    return candidates[0]


def decode_effect(
    effect_id: int,
    effect_conf: dict[int, dict],
    buff_conf: dict[int, dict],
) -> list[tuple[int, int, int, int, int]]:
    """Decode one ``EFFECT_CONF`` row into ``(handler, p0, p1, p2, p3)`` tuples."""
    rec = effect_conf.get(effect_id)
    if rec is None:
        return [(H_NOOP, effect_id, 0, 0, 0)]

    etype = rec.get("type", 0)
    params_raw = rec.get("effect_param") or rec.get("params") or []

    if etype == 1:
        candidates = collect_buff_candidates(params_raw, buff_conf)
        buff_id = pick_effect_buff(candidates, buff_conf)
        if buff_id:
            h = classify_buff_handler(buff_id, buff_conf)
            p0, p1, p2, p3 = pack_handler_params(h, buff_id, buff_conf)
            return [(h, p0, p1, p2, p3)]
        return [(H_NOOP, safe_int(params_raw, 0), safe_int(params_raw, 1), 0, 0)]

    if etype == 2:
        mode = safe_int(params_raw, 0)
        power = safe_int(params_raw, 2)
        self_damage = safe_int(params_raw, 6)
        return [(H_DAMAGE, mode, power, self_damage, 0)]

    if etype == 3:
        # State changes (buff add/remove, weather, ...) — surface as a gap;
        # specific kinds need dedicated handlers.
        return [(H_NOOP, effect_id, 0, 0, 0)]

    return [(H_NOOP, effect_id, etype, 0, 0)]


def decode_buff_direct(
    buff_id: int,
    buff_conf: dict[int, dict],
) -> list[tuple[int, int, int, int, int]]:
    """Decode a direct ``BUFF_CONF`` reference (not via ``EFFECT_CONF``)."""
    h = classify_buff_handler(buff_id, buff_conf)
    p0, p1, p2, p3 = pack_handler_params(h, buff_id, buff_conf)
    return [(h, p0, p1, p2, p3)]
