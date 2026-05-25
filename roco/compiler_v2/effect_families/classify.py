"""Source coverage bucketing + family-key derivation.

The family catalog is a pak/source audit, not the engine linker.  Coverage
therefore answers only whether compiler_v2 can emit a pak reference for a
source id.  Engine execution coverage is reported separately by
``generated/audit/engine_link_gaps.jsonl``.
"""

from __future__ import annotations

from roco.compiler_v2.effect_codegen.pak import PakTables


COVERAGE_STATUSES = frozenset({
    "pak_ref",
    "gap",
    "ability_flag",
    "ability_flag_partial",
    "mixed",
})


def _classify_one_source_id(
    sid: int,
    *,
    pak: PakTables,
    ability_flag_ids: frozenset[int],
    source_rows: list[dict] | None = None,
) -> str:
    """Report compiler source coverage for one pak source id.

    Ability-flag ids are still pak refs, but they are counted separately so
    the data-layer flag table remains visible in the audit.  No engine
    primitive/op inference happens here.
    """
    if sid in ability_flag_ids:
        return "ability_flag"
    if sid in pak.effect_conf or sid in pak.buff_conf:
        return "pak_ref"
    return "gap"

def _derive_coverage_status(breakdown: dict[str, int]) -> str:
    nonzero = {k: v for k, v in breakdown.items() if v > 0}
    if not nonzero:
        return "gap"
    if len(nonzero) == 1:
        only = next(iter(nonzero))
        return {
            "pak_ref_count": "pak_ref",
            "gap_count": "gap",
            "ability_flag_count": "ability_flag",
        }[only]
    if set(nonzero) == {"ability_flag_count", "gap_count"}:
        return "ability_flag_partial"
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
