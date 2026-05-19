"""
Effect code generation from SKILL_CONF, EFFECT_CONF, BUFF_CONF.

Classification is purely numeric — buff_base_id exact match, then prefix
family (buff_base_id // 1000) mapped to kernel handler indices via
auto-generated prefix_handler_map.json (see gen_prefix_map.py).

Data flow:
  1. Load EFFECT_CONF and BUFF_CONF tables from pak JSON files.
  2. For each skill_result entry, resolve the effect_id through EFFECT_CONF
     or BUFF_CONF and produce (handler_idx, timing, target, rate, p0-p3).
  3. handler_idx derivation:
       - BUFF_CONF refs: exact base_id map, then prefix family map
       - EFFECT_CONF type=1: resolve to buff, then classify
       - EFFECT_CONF type=2: H_DAMAGE
       - EFFECT_CONF type=3: H_NOOP
  4. Timing = cast_moment directly.
  5. Target = result_target_type (1=self, 2/3=enemy).
  6. Rate = success_rate raw (10000 = 100%).

Output: flat tuples that artifact.py emits into catalog_hot.py.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from roco.compiler.effect_model import Timing


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


# Handler indices — auto-generated from HANDLERS array in ops.py.
# Run `uv run python -m roco.compiler.gen_prefix_map` to regenerate.
from roco.compiler.generated.handler_indices import *  # noqa: F401,F403


# ---------------------------------------------------------------------------
# Prefix→handler mapping: loaded from auto-generated JSON.
# Run `uv run python -m roco.compiler.gen_prefix_map` to regenerate.
# ---------------------------------------------------------------------------

_MAP_PATH = Path(__file__).resolve().parent / "generated" / "prefix_handler_map.json"


def _load_handler_maps() -> tuple[dict[int, int], dict[int, int]]:
    if not _MAP_PATH.exists():
        return {}, {}
    data = json.loads(_MAP_PATH.read_text(encoding="utf-8"))
    prefix_map = {int(k): v for k, v in data.get("prefix_map", {}).items()}
    base_id_map = {int(k): v for k, v in data.get("base_id_map", {}).items()}
    return prefix_map, base_id_map


_PREFIX_HANDLER_MAP, _BASE_ID_HANDLER_MAP = _load_handler_maps()


def _pack_handler_params(h: int, buff_id: int, buff_conf: dict[int, dict]) -> tuple[int, int, int, int]:
    """Pack kernel-compatible params for the given handler index.

    Each kernel handler reads specific semantics from p0-p3.
    This function extracts those values from the pak buff data.
    """
    rec = buff_conf.get(buff_id) or {}
    base_ids = [bid for bid in (rec.get("buff_base_ids") or []) if bid]

    # Status effects: p0 = stack count (default 1)
    if h in (H_BURN, H_POISON, H_FREEZE, H_LEECH):
        return (1, 0, 0, 0)

    # Mark handlers: p0 = stack count (default 1)
    if H_POISON_MARK <= h <= H_MOMENTUM_MARK:
        return (1, 0, 0, 0)

    # Stat buffs/debuffs: p0-p3 = packed buff stages (buff_base_ids)
    if h in (H_SELF_BUFF, H_ENEMY_DEBUFF, H_SELF_DEBUFF):
        p = (base_ids + [0, 0, 0, 0])[:4]
        return (p[0], p[1], p[2], p[3])

    # Default: pass through buff_base_ids as params
    p = (base_ids + [0, 0, 0, 0])[:4]
    return (p[0], p[1], p[2], p[3])


def _classify_buff_handler(buff_id: int, buff_conf: dict[int, dict]) -> int:
    """Classify a BUFF_CONF record into a handler index.

    Pure numeric: exact buff_base_id match, then prefix family fallback.
    """
    rec = buff_conf.get(buff_id)
    if rec is None:
        return H_NOOP
    base_ids = rec.get("buff_base_ids") or []
    for bid in base_ids:
        if bid and bid in _BASE_ID_HANDLER_MAP:
            return _BASE_ID_HANDLER_MAP[bid]
    for bid in base_ids:
        if bid:
            h = _PREFIX_HANDLER_MAP.get(bid // 1000, H_NOOP)
            if h != H_NOOP:
                return h
    return H_NOOP


# ---------------------------------------------------------------------------
# Decode EFFECT_CONF entries
# ---------------------------------------------------------------------------

def _decode_effect(
    effect_id: int,
    effect_conf: dict[int, dict],
    buff_conf: dict[int, dict],
) -> list[tuple[int, int, int, int, int]]:
    """Decode an EFFECT_CONF entry into (handler_idx, p0, p1, p2, p3) tuples."""
    rec = effect_conf.get(effect_id)
    if rec is None:
        return [(H_NOOP, effect_id, 0, 0, 0)]

    etype = rec.get("type", 0)
    params_raw = rec.get("effect_param") or rec.get("params") or []

    if etype == 1:
        # Scan all param positions for a valid buff_id (pak puts them in varying slots)
        buff_id = 0
        for idx in range(len(params_raw)):
            candidate = _safe_int(params_raw, idx)
            if candidate and candidate in buff_conf:
                buff_id = candidate
                break
        if buff_id:
            h = _classify_buff_handler(buff_id, buff_conf)
            p0, p1, p2, p3 = _pack_handler_params(h, buff_id, buff_conf)
            return [(h, p0, p1, p2, p3)]
        return [(H_NOOP, _safe_int(params_raw, 0), _safe_int(params_raw, 1), 0, 0)]

    elif etype == 2:
        mode = _safe_int(params_raw, 0)
        power = _safe_int(params_raw, 2)
        self_damage = _safe_int(params_raw, 6)
        return [(H_DAMAGE, mode, power, self_damage, 0)]

    elif etype == 3:
        # State changes are varied (buff add/remove, weather, etc.).
        # Only classify as an effect when we can determine the intent.
        # Default to NOOP — specific state changes should be handled via
        # manual overrides or more targeted classification.
        return [(H_NOOP, effect_id, 0, 0, 0)]

    else:
        # Unknown effect type.
        return [(H_NOOP, effect_id, etype, 0, 0)]


# ---------------------------------------------------------------------------
# Decode BUFF_CONF entries (direct buff reference, not via EFFECT_CONF)
# ---------------------------------------------------------------------------

def _decode_buff_direct(
    buff_id: int,
    buff_conf: dict[int, dict],
) -> list[tuple[int, int, int, int, int]]:
    """Decode a direct BUFF_CONF reference into (handler_idx, p0, p1, p2, p3)."""
    h = _classify_buff_handler(buff_id, buff_conf)
    p0, p1, p2, p3 = _pack_handler_params(h, buff_id, buff_conf)
    return [(h, p0, p1, p2, p3)]


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
            decoded = [(H_NOOP, effect_id, 0, 0, 0)]

        for handler_idx, p0, p1, p2, p3 in decoded:
            if handler_idx != H_NOOP:
                results.append((handler_idx, timing, target, success_rate, p0, p1, p2, p3))

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
