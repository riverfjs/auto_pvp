"""Gap audit: explain *why* a pak effect resolved to H_NOOP.

The codegen pipeline used to silently discard any decode that produced
H_NOOP, which made downstream coverage gaps invisible.  This module
collects the same buff metadata the classifier saw and tags it with a
short ``reason`` so the SQLite ``effect_gaps`` table records auditable
drops keyed by the primitive (``effect_<id>`` / ``buff_<id>`` /
``prefix_<n>``) that needs work.
"""

from __future__ import annotations

from roco.generated.handler_indices import H_NOOP

from roco.compiler.effect_codegen.classify import (
    BASE_ID_HANDLER_MAP,
    PREFIX_HANDLER_MAP,
    collect_buff_candidates,
    pick_effect_buff,
)
from roco.compiler.effect_codegen.pak import PakTables


def resolve_buff_metadata(
    effect_id: int,
    pak_data: PakTables,
) -> tuple[int, list[int]]:
    """Locate the buff_id and ``buff_base_ids`` the classifier acted on.

    Mirrors :func:`pick_effect_buff` so the gap audit reports the same buff
    the runtime classifier dropped.  Returns ``(0, [])`` when no buff can
    be located.
    """
    if effect_id in pak_data.buff_conf:
        rec = pak_data.buff_conf[effect_id]
        return effect_id, [int(b) for b in (rec.get("buff_base_ids") or []) if b]
    rec = pak_data.effect_conf.get(effect_id)
    if rec is None:
        return 0, []
    params_raw = rec.get("effect_param") or rec.get("params") or []
    candidates = collect_buff_candidates(params_raw, pak_data.buff_conf)
    chosen = pick_effect_buff(candidates, pak_data.buff_conf)
    if not chosen:
        return 0, []
    buff_rec = pak_data.buff_conf[chosen]
    return chosen, [int(b) for b in (buff_rec.get("buff_base_ids") or []) if b]


def gap_reason(
    effect_id: int,
    buff_id: int,
    base_ids: list[int],
    pak_data: PakTables,
) -> tuple[str, str]:
    """Classify *why* a decode produced H_NOOP.

    Returns ``(reason, primitive)``.  ``primitive`` is the short identifier
    used as the gap's de-facto key (``effect_<id>`` / ``buff_<id>`` /
    ``prefix_<n>``).  ``reason`` distinguishes structural cases:

    * ``effect_id_not_in_pak`` — the skill references an id the pak tables
      do not contain.
    * ``effect_type_3_state_change`` — generic state-change effect; needs a
      dedicated handler when used.
    * ``effect_type_{n}_unknown`` — pak type field the decoder does not
      recognise.
    * ``effect_type_1_no_buff`` — type=1 effect whose params contain no
      buff_id present in BUFF_CONF.
    * ``buff_no_base_ids`` — buff record exists but is empty (a stub).
    * ``prefix_{n}_intentional_noop`` — prefix is in the codegen seed but
      maps to H_NOOP on purpose (e.g. detection, cooldown).
    * ``prefix_{n}_unmapped`` — prefix not seeded; coverage hole.
    * ``buff_unclassified`` / ``unclassified`` — fall-through.
    """
    if effect_id not in pak_data.effect_conf and effect_id not in pak_data.buff_conf:
        return "effect_id_not_in_pak", f"effect_{effect_id}"
    if effect_id in pak_data.effect_conf:
        etype = pak_data.effect_conf[effect_id].get("type", 0)
        if etype == 3:
            return "effect_type_3_state_change", f"effect_{effect_id}"
        if etype not in (1, 2):
            return f"effect_type_{etype}_unknown", f"effect_{effect_id}"
        if buff_id == 0:
            return "effect_type_1_no_buff", f"effect_{effect_id}"
    if buff_id and not base_ids:
        return "buff_no_base_ids", f"buff_{buff_id}"
    if base_ids:
        for bid in base_ids:
            if bid in BASE_ID_HANDLER_MAP:
                continue
            pfx = bid // 1000
            mapped = PREFIX_HANDLER_MAP.get(pfx, H_NOOP)
            if mapped == H_NOOP:
                if pfx in PREFIX_HANDLER_MAP:
                    return f"prefix_{pfx}_intentional_noop", f"prefix_{pfx}"
                return f"prefix_{pfx}_unmapped", f"prefix_{pfx}"
        return "buff_unclassified", f"buff_{buff_id}"
    return "unclassified", f"effect_{effect_id}"
