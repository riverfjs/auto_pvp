"""Gap-row metadata helper.

After the four-state (Emit / Ignored / Gap / AbilityFlag) refactor, gap classification lives inside the
decoders themselves (see :mod:`.classify`).  This module retains only
:func:`resolve_buff_metadata` for downstream tools that want to walk
an effect_id and report its associated buff_id / base_ids (e.g.
ad-hoc audit scripts).  Nothing in the compile pipeline imports from
here any more.
"""

from __future__ import annotations

from roco.compiler.effect_codegen.classify import collect_buff_candidates
from roco.compiler.effect_codegen.pak import PakTables


def resolve_buff_metadata(
    effect_id: int,
    pak_data: PakTables,
) -> tuple[int, list[int]]:
    """Locate one buff_id referenced by ``effect_id`` for audit reporting.

    Returns the buff_id (or 0) and its ``buff_base_ids``.  When pak
    references several buffs (a compound effect), the first slot wins
    here purely so the report has *something* concrete to point at.
    """
    if effect_id in pak_data.buff_conf:
        rec = pak_data.buff_conf[effect_id]
        return effect_id, [int(b) for b in (rec.get("buff_base_ids") or []) if b]
    rec = pak_data.effect_conf.get(effect_id)
    if rec is None:
        return 0, []
    params_raw = rec.get("effect_param") or rec.get("params") or []
    candidates = collect_buff_candidates(params_raw, pak_data.buff_conf)
    if not candidates:
        return 0, []
    chosen = candidates[0]
    buff_rec = pak_data.buff_conf[chosen]
    return chosen, [int(b) for b in (buff_rec.get("buff_base_ids") or []) if b]
