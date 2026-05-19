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

from roco.common.enums import WeatherType
from roco.generated.handler_indices import (
    H_BURN,
    H_DAMAGE,
    H_DISPEL_MARKS,
    H_NOOP,
    H_SELF_BUFF,
    H_WEATHER,
)

from roco.compiler.effect_codegen.params import (
    extract_int_list,
    is_status_or_mark_handler,
    pack_handler_params,
    safe_int,
)


# Exact ``effect_id`` → kernel row override.  Used for pak effects that:
#   * mean something the prefix/base-id scan cannot classify
#     (1028xxx state-change weather effects — type=3 with a pak-internal
#     weather code that no buff_base_id ever expresses);
#   * are compound semantics where the heuristic picker would pick the
#     wrong slot (1042014 "标记转换灼烧" — five burn buffs packed in slot 2
#     after a marker buff in slot 1).
#
# Tuple shape: ``(handler_idx, p0, p1, p2, p3, timing_override)``.
# ``timing_override = 0`` keeps the skill_result's own ``cast_moment``;
# any non-zero value overrides it (used for 1042014 because the kernel
# only runs skill effects at BEFORE_MOVE/CALC_DAMAGE/AFTER_MOVE today —
# turn-end skill processing is a separate kernel project).
EXACT_EFFECT_OVERRIDES: dict[int, tuple[int, int, int, int, int, int]] = {
    # Weather setters — pak param[0] is a pak-internal weather code; map to
    # the kernel's WeatherType enum and seed an 8-turn duration so the
    # first end-of-turn tick lands the test expectation of 7 turns left.
    1028001: (H_WEATHER, WeatherType.RAIN.value,      8, 0, 0, 0),  # 求雨
    1028003: (H_WEATHER, WeatherType.SANDSTORM.value, 8, 0, 0, 0),  # 沙暴
    1028004: (H_WEATHER, WeatherType.NONE.value,      0, 0, 0, 0),  # 晴天 (clear weather)
    1028005: (H_WEATHER, WeatherType.SNOW.value,      8, 0, 0, 0),  # 暴风雪
    # 场地转换标记 — pak crams two dozen mark buff_ids into one slot to
    # signal "dispel all marks both sides", not "apply wind/water/...".
    1042008: (H_DISPEL_MARKS, 0, 0, 0, 0, 0),
    # 标记转换灼烧 — game text says "for each dispelled mark, apply 5 burn
    # stacks".  Without a dedicated kernel op that counts dispelled marks,
    # emit a fixed 5-stack burn at the pak-declared cast_moment (TURN_END,
    # now handled by ``tick_skill_turn_end``).  Replace when a
    # marks→burn primitive lands.
    1042014: (H_BURN, 5, 0, 0, 0, 0),
}


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
) -> list[tuple[int, int, int, int, int, int]]:
    """Decode one ``EFFECT_CONF`` row into ``(handler, p0..p3, raw_stacks)`` tuples.

    ``raw_stacks`` is the stack count inferred from pak — i.e. how many times
    the chosen buff repeats in its slot.  Callers override it with
    ``buff_group_level`` from the skill_result entry when that field is set.
    """
    rec = effect_conf.get(effect_id)
    if rec is None:
        return [(H_NOOP, effect_id, 0, 0, 0, 1)]

    etype = rec.get("type", 0)
    params_raw = rec.get("effect_param") or rec.get("params") or []

    if etype == 1:
        candidates = collect_buff_candidates(params_raw, buff_conf)
        buff_id = pick_effect_buff(candidates, buff_conf)
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
        # State changes (buff add/remove, weather, ...) — surface as a gap;
        # specific kinds need dedicated handlers.
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
