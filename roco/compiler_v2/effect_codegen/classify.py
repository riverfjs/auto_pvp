"""Pak-effect classification — pak-first primitive output.

Each decoder returns ``list[EmitOutcome | GapOutcome]``
(never engine handler rows).  See :mod:`.outcomes` for the four-state contract.

Dispatch for ``EFFECT_CONF`` rows (see :func:`decode_effect`):

* Any existing ``EFFECT_CONF`` row emits ``effect_ref:<id>``.
* Any existing ``BUFF_CONF`` row emits ``buff_ref:<id>``.

``classify_buff_primitive`` (exact ``buff_id``/``buff_base_id`` then pak
order/prefix) is also
kept for generated axis/audit artifacts, but runtime row generation no
longer consumes it.
"""

from __future__ import annotations

from roco.common.primitive_keys import buff_ref_key, effect_ref_key
from roco.compiler_v2.build import build_static_bundle
from roco.compiler_v2.effect_codegen.outcomes import EmitOutcome, GapOutcome
from roco.compiler_v2.effect_codegen.params import (
    extract_int_list,
)
from roco.compiler_v2.primitive_map_builder import build_primitive_map


def _load_primitive_maps() -> tuple[dict[int, str], dict[int, str], dict[int, str], dict[int, str]]:
    """Build buff-primitive lookup tables directly from pak/Lua source.

    Returns ``(buff_id_map, prefix_map, base_id_map, base_id_via_order_map)``.
    The first table handles pak-visible exact buff identities such as mark
    buffs that reuse generic base rows.  ``via_order`` is the pak-axis pre-join
    of ``BUFFBASE_CONF.buffbase_order`` → primitive, and ``prefix_map`` is the
    remaining mixed-prefix family map.
    """
    data = build_primitive_map(build_static_bundle())
    buff_id_map = {int(k): str(v) for k, v in data.get("buff_id_map", {}).items()}
    prefix_map = {int(k): str(v) for k, v in data.get("prefix_map", {}).items()}
    base_id_map = {int(k): str(v) for k, v in data.get("base_id_map", {}).items()}
    via_order_map = {
        int(k): str(v) for k, v in data.get("base_id_via_order_map", {}).items()
    }
    return buff_id_map, prefix_map, base_id_map, via_order_map


BUFF_ID_PRIMITIVE_MAP, PREFIX_PRIMITIVE_MAP, BASE_ID_PRIMITIVE_MAP, BASE_ID_VIA_ORDER_MAP = _load_primitive_maps()


def classify_buff_primitive(buff_id: int, buff_conf: dict[int, dict]) -> str:
    """Map a buff_id to a primitive string via the generated axis stack.

    Lookup order:

    1. Exact ``BUFF_CONF.id`` map (``BUFF_ID_PRIMITIVE_MAP``).  Generated
       from pak-visible semantic identities whose base rows are shared.
    2. Exact ``base_id`` anchors (``BASE_ID_PRIMITIVE_MAP``), generated from
       engine-owned semantic names resolved through current pak data.
    3. Pak-axis ``buffbase_order`` resolution
       (``BASE_ID_VIA_ORDER_MAP``).  This is the primary axis post-7C —
       most buff families dispatch here.
    4. Legacy ``prefix`` map (``PREFIX_PRIMITIVE_MAP``).  Only the few
       prefixes whose buffbase_order distribution is not 100% concen-
       trated remain at this layer; everything else has been migrated.

    Returns "" when no mapping exists; callers must convert it into a
    :class:`GapOutcome` rather than emitting a runtime row.
    """
    rec = buff_conf.get(buff_id)
    if rec is None:
        return ""
    primitive = BUFF_ID_PRIMITIVE_MAP.get(buff_id, "")
    if primitive:
        return primitive
    base_ids = rec.get("buff_base_ids") or []
    for bid in base_ids:
        if bid and bid in BASE_ID_PRIMITIVE_MAP:
            return BASE_ID_PRIMITIVE_MAP[bid]
    for bid in base_ids:
        if bid and bid in BASE_ID_VIA_ORDER_MAP:
            return BASE_ID_VIA_ORDER_MAP[bid]
    for bid in base_ids:
        if bid:
            primitive = PREFIX_PRIMITIVE_MAP.get(bid // 1000, "")
            if primitive:
                return primitive
    return ""


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


def _buff_gap(effect_id: int | None, buff_id: int, buff_conf: dict[int, dict]) -> GapOutcome:
    """Build a GapOutcome for a buff classification miss.

    ``classify_buff_primitive`` returned "" — figure out *why* and pick a
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
    # the prefix is absent from PREFIX_PRIMITIVE_MAP or it is present with
    # an empty primitive (defensive — the generator no longer emits empty
    # values, but treat both shapes the same so a stale primitive map
    # can't silently shadow gaps as ``buff_unclassified``).
    for bid in base_ids:
        pfx = bid // 1000
        if bid in BASE_ID_PRIMITIVE_MAP:
            continue
        if bid in BASE_ID_VIA_ORDER_MAP:
            continue
        if not PREFIX_PRIMITIVE_MAP.get(pfx, ""):
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
    # Every base_id has a mapped prefix but the caller still rejected it —
    # keep a precise fall-through.
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
) -> list[EmitOutcome | GapOutcome]:
    """Emit a pak ``EFFECT_CONF`` reference without interpreting behavior."""
    rec = effect_conf.get(effect_id)
    if rec is None:
        return [GapOutcome(
            primitive=f"effect_{effect_id}",
            effect_id=effect_id,
            buff_id=None,
            reason="effect_id_not_in_pak",
            params={"effect_id": effect_id},
        )]
    return [EmitOutcome(effect_ref_key(effect_id), 0, 0, 0, 0, 1)]


def decode_buff_direct(
    buff_id: int,
    buff_conf: dict[int, dict],
) -> list[EmitOutcome | GapOutcome]:
    """Emit a pak ``BUFF_CONF`` reference without interpreting behavior."""
    if buff_id in buff_conf:
        return [EmitOutcome(buff_ref_key(buff_id), 0, 0, 0, 0, 1)]
    return [_buff_gap(None, buff_id, buff_conf)]
