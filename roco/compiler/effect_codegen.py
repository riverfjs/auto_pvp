"""
Pak-native effect code generation from SKILL_CONF, EFFECT_CONF, BUFF_CONF.

Replaces the old keyword/regex classification pipeline with direct structural
lookups against pak game tables.  No text matching is needed because PakOp IS
the classification -- it is the buff_base_id prefix family itself.

Data flow:
  1. Load EFFECT_CONF and BUFF_CONF tables from pak JSON files.
  2. For each skill_result entry, resolve the effect_id through EFFECT_CONF
     or BUFF_CONF and produce (pak_op, timing, target, rate, p0, p1, p2, p3)
     tuples.
  3. pak_op derivation:
       - BUFF_CONF refs: first buff_base_id // 1000 (prefix family)
       - EFFECT_CONF type=1: resolve to buff, then prefix family
       - EFFECT_CONF type=2: EFF_DAMAGE (10002)
       - EFFECT_CONF type=3: EFF_STATE_CHANGE (10003)
  4. Timing = cast_moment value directly (matches Timing enum).
  5. Target = result_target_type (1=self, 2/3=enemy).
  6. Rate = success_rate raw value (10000 = 100%).
  7. Params (p0-p3): raw values from effect_param or buff_base_ids.

Output: flat tuples that artifact.py can directly emit into catalog_hot.py.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from roco.compiler.effect_model import PakOp, Timing


# ---------------------------------------------------------------------------
# Pak table loading
# ---------------------------------------------------------------------------

def _load_pak_table(path: Path) -> dict[int, dict[str, Any]]:
    """Load a pak BinData JSON table and return keyed by integer id."""
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    rows = data.get("RocoDataRows", data)
    if not isinstance(rows, dict):
        raise ValueError(f"unexpected table format: {path}")
    return {int(k): v for k, v in rows.items()}


class PakTables:
    """Lazy-loaded pak data tables needed for effect codegen."""

    def __init__(self, pak_data_dir: Path):
        self._dir = pak_data_dir / "BinData"
        self._effect_conf: dict[int, dict] | None = None
        self._buff_conf: dict[int, dict] | None = None
        self._skill_conf: dict[int, dict] | None = None

    @property
    def effect_conf(self) -> dict[int, dict]:
        if self._effect_conf is None:
            self._effect_conf = _load_pak_table(self._dir / "EFFECT_CONF.json")
        return self._effect_conf

    @property
    def buff_conf(self) -> dict[int, dict]:
        if self._buff_conf is None:
            self._buff_conf = _load_pak_table(self._dir / "BUFF_CONF.json")
        return self._buff_conf

    @property
    def skill_conf(self) -> dict[int, dict]:
        if self._skill_conf is None:
            self._skill_conf = _load_pak_table(self._dir / "SKILL_CONF.json")
        return self._skill_conf


# ---------------------------------------------------------------------------
# PakOp membership set (for fast validation)
# ---------------------------------------------------------------------------

_PAKOP_VALUES = frozenset(int(v) for v in PakOp)


def _to_pak_op(value: int) -> int:
    """Return value if it is a valid PakOp, else UNSUPPORTED."""
    return value if value in _PAKOP_VALUES else PakOp.UNSUPPORTED


# ---------------------------------------------------------------------------
# Param extraction helpers
# ---------------------------------------------------------------------------

def _unwrap_param(lst: list, index: int) -> Any:
    """Extract raw value from pak effect_param at *index*.

    pak effect_param is ``[{"params": [v1]}, {"params": [v2]}, ...]``.
    Returns the first element of the inner ``params`` list, or the
    item itself if it's already a plain value.
    """
    if index >= len(lst):
        return None
    item = lst[index]
    if isinstance(item, dict):
        inner = item.get("params", [])
        if isinstance(inner, list) and inner:
            return inner[0] if len(inner) == 1 else inner
        return None
    return item


def _safe_int(lst: list, index: int, default: int = 0) -> int:
    """Safely extract an int from a pak param list by index."""
    val = _unwrap_param(lst, index)
    if val is None:
        return default
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def _extract_int_list(lst: list, index: int) -> list[int]:
    """Extract a single int or list of ints from a param position."""
    val = _unwrap_param(lst, index)
    if val is None:
        return []
    if isinstance(val, list):
        return [int(v) for v in val if v]
    if isinstance(val, (int, float)) and val:
        return [int(val)]
    return []


# ---------------------------------------------------------------------------
# Resolve buff_base_id -> PakOp prefix family
# ---------------------------------------------------------------------------

def _buff_base_to_pak_op(buff_base_id: int) -> int:
    """Derive PakOp from a buff_base_id by taking the prefix family (// 1000)."""
    if not buff_base_id:
        return PakOp.UNSUPPORTED
    prefix = buff_base_id // 1000
    return _to_pak_op(prefix)


def _resolve_buff_pak_op(buff_id: int, buff_conf: dict[int, dict]) -> tuple[int, list[int]]:
    """Resolve a buff_id to (pak_op, buff_base_ids).

    Returns the PakOp from the first non-zero buff_base_id, plus the
    full list of buff_base_ids for param packing.
    """
    rec = buff_conf.get(buff_id)
    if rec is None:
        return PakOp.UNSUPPORTED, []
    base_ids = [bid for bid in (rec.get("buff_base_ids") or []) if bid]
    if not base_ids:
        return PakOp.UNSUPPORTED, []
    pak_op = _buff_base_to_pak_op(base_ids[0])
    return pak_op, base_ids


# ---------------------------------------------------------------------------
# Decode EFFECT_CONF entries
# ---------------------------------------------------------------------------

def _decode_effect(
    effect_id: int,
    effect_conf: dict[int, dict],
    buff_conf: dict[int, dict],
) -> list[tuple[int, int, int, int, int]]:
    """Decode an EFFECT_CONF entry into (pak_op, p0, p1, p2, p3) tuples.

    EFFECT_CONF type dispatch:
      type=1: buff application.  effect_param[0] contains a buff_id.
      type=2: damage effect.  Params: mode, power, self_damage.
      type=3: state change / dispel.
    """
    rec = effect_conf.get(effect_id)
    if rec is None:
        return [(PakOp.UNSUPPORTED, effect_id, 0, 0, 0)]

    etype = rec.get("type", 0)
    params_raw = rec.get("effect_param") or rec.get("params") or []

    if etype == 1:
        # Buff application: resolve buff_id from params to get PakOp.
        buff_id = _safe_int(params_raw, 0)
        if buff_id and buff_id in buff_conf:
            pak_op, base_ids = _resolve_buff_pak_op(buff_id, buff_conf)
            # Pack up to 4 buff_base_ids as params.
            p = (base_ids + [0, 0, 0, 0])[:4]
            return [(pak_op, p[0], p[1], p[2], p[3])]
        # Fallback: try second param position.
        buff_id = _safe_int(params_raw, 1)
        if buff_id and buff_id in buff_conf:
            pak_op, base_ids = _resolve_buff_pak_op(buff_id, buff_conf)
            p = (base_ids + [0, 0, 0, 0])[:4]
            return [(pak_op, p[0], p[1], p[2], p[3])]
        return [(PakOp.EFF_BUFF_APPLY, _safe_int(params_raw, 0), _safe_int(params_raw, 1), 0, 0)]

    elif etype == 2:
        # Damage effect: mode, power, self_damage.
        mode = _safe_int(params_raw, 0)
        power = _safe_int(params_raw, 2)
        self_damage = _safe_int(params_raw, 6)
        return [(PakOp.EFF_DAMAGE, mode, power, self_damage, 0)]

    elif etype == 3:
        # State change / dispel.
        remove_ids = _extract_int_list(params_raw, 1)
        p0 = remove_ids[0] if len(remove_ids) > 0 else 0
        p1 = remove_ids[1] if len(remove_ids) > 1 else 0
        p2 = remove_ids[2] if len(remove_ids) > 2 else 0
        p3 = remove_ids[3] if len(remove_ids) > 3 else 0
        return [(PakOp.EFF_STATE_CHANGE, p0, p1, p2, p3)]

    else:
        # Unknown effect type.
        return [(PakOp.UNSUPPORTED, effect_id, etype, 0, 0)]


# ---------------------------------------------------------------------------
# Decode BUFF_CONF entries (direct buff reference, not via EFFECT_CONF)
# ---------------------------------------------------------------------------

def _decode_buff_direct(
    buff_id: int,
    buff_conf: dict[int, dict],
) -> list[tuple[int, int, int, int, int]]:
    """Decode a direct BUFF_CONF reference into (pak_op, p0, p1, p2, p3)."""
    pak_op, base_ids = _resolve_buff_pak_op(buff_id, buff_conf)
    p = (base_ids + [0, 0, 0, 0])[:4]
    return [(pak_op, p[0], p[1], p[2], p[3])]


# ---------------------------------------------------------------------------
# Public API: generate effect rows
# ---------------------------------------------------------------------------

def generate_effect_rows(
    skill_row: dict,
    pak_data: PakTables,
) -> list[tuple[int, ...]]:
    """Generate (pak_op, timing, target, rate, p0, p1, p2, p3) tuples for a skill.

    Parameters
    ----------
    skill_row : dict
        A single SKILL_CONF record.  Expected to have ``skill_result``.
    pak_data : PakTables
        Loaded pak data tables.

    Returns
    -------
    list[tuple[int, ...]]
        Each tuple is (pak_op, timing, target, rate, p0, p1, p2, p3).
    """
    results: list[tuple[int, ...]] = []
    skill_results = skill_row.get("skill_result") or []

    for entry in skill_results:
        effect_id = entry.get("effect_id", 0)
        cast_moment = entry.get("cast_moment", 11)
        target_type = entry.get("result_target_type", 1)
        success_rate = entry.get("success_rate", 10000)

        # Timing is cast_moment directly.
        timing = cast_moment

        # Target: 1=self, 2/3=enemy.
        target = target_type

        # Resolve effect_id through EFFECT_CONF first, then BUFF_CONF.
        if effect_id in pak_data.effect_conf:
            decoded = _decode_effect(effect_id, pak_data.effect_conf, pak_data.buff_conf)
        elif effect_id in pak_data.buff_conf:
            decoded = _decode_buff_direct(effect_id, pak_data.buff_conf)
        else:
            decoded = [(PakOp.UNSUPPORTED, effect_id, 0, 0, 0)]

        for pak_op, p0, p1, p2, p3 in decoded:
            results.append((pak_op, timing, target, success_rate, p0, p1, p2, p3))

    return results


def build_ability_effect_rows(
    ability_row: dict,
    pak_data: PakTables,
) -> list[tuple[int, ...]]:
    """Generate (pak_op, timing, target, rate, p0, p1, p2, p3) tuples for an ability.

    Abilities use the same ``skill_result`` structure as skills in pak data,
    so this delegates to :func:`generate_effect_rows`.  Falls back to
    ``effect_list`` key if ``skill_result`` is absent.
    """
    if "skill_result" not in ability_row and "effect_list" in ability_row:
        ability_row = dict(ability_row)
        ability_row["skill_result"] = ability_row["effect_list"]

    return generate_effect_rows(ability_row, pak_data)


# ---------------------------------------------------------------------------
# Gap / coverage reporting
# ---------------------------------------------------------------------------

def report_coverage(
    pak_data: PakTables,
) -> dict[str, Any]:
    """Scan all BUFF_CONF base_ids and report PakOp coverage.

    Returns
    -------
    dict
        ``total``       : total unique buff_base_ids found
        ``mapped``      : count with a valid PakOp (not UNSUPPORTED)
        ``unmapped``    : count that resolve to UNSUPPORTED
        ``coverage_pct``: float 0-100
        ``op_dist``     : dict[str, int] PakOp name -> count
    """
    from collections import Counter

    base_ids: set[int] = set()
    for rec in pak_data.buff_conf.values():
        for bid in (rec.get("buff_base_ids") or []):
            if bid:
                base_ids.add(bid)

    op_counts: Counter[str] = Counter()
    unmapped: list[int] = []
    for bid in sorted(base_ids):
        pak_op = _buff_base_to_pak_op(bid)
        if pak_op == PakOp.UNSUPPORTED:
            unmapped.append(bid)
            op_counts["UNSUPPORTED"] += 1
        else:
            op_counts[PakOp(pak_op).name] += 1

    total = len(base_ids)
    mapped = total - len(unmapped)
    return {
        "total": total,
        "mapped": mapped,
        "unmapped": len(unmapped),
        "coverage_pct": round(mapped / total * 100, 2) if total else 0.0,
        "unmapped_ids": unmapped,
        "op_dist": dict(op_counts.most_common()),
    }
