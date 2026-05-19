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
# Handler index assignment from pak data.
# These indices match the HANDLERS array in roco.engine.kernel.ops.
# Classification is done here (data layer), not in the kernel.
# ---------------------------------------------------------------------------

H_NOOP = 0
H_DAMAGE = 1
H_LIFE_DRAIN = 2
H_DAMAGE_REDUCE = 3
H_STAT_BUFF = 4
H_STAT_DEBUFF = 5
H_SELF_DEBUFF = 6
H_BURN = 7
H_POISON = 8
H_FREEZE = 9
H_LEECH = 10
H_HEAL_HP = 11
H_HEAL_ENERGY = 12
H_STEAL_ENERGY = 13
H_ENEMY_LOSE_ENERGY = 14
H_FORCE_SWITCH = 15
H_WEATHER = 16
H_CLEANSE = 17
H_POWER_MOD = 18
H_COST_UP = 19
H_COST_REDUCE = 20
H_HIT_COUNT = 21
H_CUTE_GAIN = 22
H_CUTE_ENEMY = 23
H_CUTE_BOTH = 24
H_FORCE_ENEMY_SWITCH = 25
H_COUNTER_ATTACK = 26
H_INTERRUPT = 27
H_ENERGY_ALL_IN = 28
H_HP_FOR_ENERGY = 29
H_ANTI_HEAL = 30
# Mark handlers (31-47)
H_POISON_MARK = 31
H_MOISTURE_MARK = 32
H_DRAGON_MARK = 33
H_WIND_MARK = 34
H_CHARGE_MARK = 35
H_SOLAR_MARK = 36
H_ATTACK_MARK = 37
H_SLOW_MARK = 38
H_SLUGGISH_MARK = 39
H_SPIRIT_MARK = 40
H_METEOR_MARK = 41
H_THORN_MARK = 42
H_MOMENTUM_MARK = 43
H_DISPEL_ENEMY_MARKS = 44
H_CONSUME_MARKS_HEAL = 45
H_DISPEL_MARKS = 46
H_CONVERT_POISON_TO_MARK = 47
# Additional handlers (48+)
H_PERMANENT_MOD = 48
H_GRANT_LIFE_DRAIN = 49
H_ENERGY_REGEN = 50


# Mark-related buff_base_id patterns: buff_base_id -> mark handler index
_MARK_BASE_ID_MAP: dict[int, int] = {
    2032007: H_MOISTURE_MARK,  # 湿润印记
    2021004: H_WIND_MARK,      # 风起印记
    2007001: H_POISON_MARK,    # 通用中毒 (as mark)
    2005001: H_LEECH,          # 寄生种子
}


# PakOp prefix family -> default kernel handler index.
# Used as fallback when text-based classification misses.
_PAKOP_HANDLER_MAP: dict[int, int] = {
    PakOp.STAT_MOD: H_STAT_BUFF,
    PakOp.LEECH: H_LEECH,
    PakOp.STATUS_CONDITION: H_POISON,
    PakOp.DAMAGE_REDUCE: H_DAMAGE_REDUCE,
    PakOp.STUN_HEAL: H_HIT_COUNT,
    PakOp.COST_MOD: H_COST_REDUCE,
    PakOp.POWER_MOD: H_POWER_MOD,
    PakOp.PRIORITY: H_POWER_MOD,
    PakOp.HIT_COUNT: H_HIT_COUNT,
    PakOp.DRAIN: H_LIFE_DRAIN,
    PakOp.HEAL_MOD: H_HEAL_HP,
    PakOp.ENERGY_GAIN: H_HEAL_ENERGY,
    PakOp.FORCE_SWITCH: H_FORCE_SWITCH,
    PakOp.SURVIVAL: H_DAMAGE_REDUCE,
    PakOp.CUTE_SPEED: H_CUTE_GAIN,
    PakOp.DRIVE: H_HIT_COUNT,
    PakOp.DYNAMIC_HIT: H_HIT_COUNT,
    PakOp.ELEMENT_TRIGGER: H_STAT_BUFF,
    PakOp.ON_HIT_REACTION: H_STAT_BUFF,
    PakOp.COUNTER_REWARD: H_STAT_BUFF,
    PakOp.CONDITIONAL_TRIGGER: H_STAT_BUFF,
    PakOp.NEXT_PET: H_STAT_BUFF,
    PakOp.CANDY: H_CUTE_GAIN,
    PakOp.EFFICIENCY: H_COST_REDUCE,
    PakOp.NUTRITION: H_HEAL_HP,
    PakOp.COND_POWER: H_POWER_MOD,
    PakOp.FLAT_POWER: H_POWER_MOD,
    PakOp.ON_KILL: H_STAT_BUFF,
    PakOp.LOCK_SWITCH: H_STAT_BUFF,
    PakOp.IMMUNITY_LOCK: H_STAT_BUFF,
    PakOp.PURIFY: H_CLEANSE,
    PakOp.FREEZE_STATUS: H_FREEZE,
    PakOp.BOSS_STUN: H_STAT_BUFF,
    PakOp.FIRE_RAGE: H_POWER_MOD,
    PakOp.CHARGE: H_STAT_BUFF,
    PakOp.DOUBLE_ACTION: H_STAT_BUFF,
    PakOp.ELEMENT_ENERGY: H_HEAL_ENERGY,
    PakOp.OVERLOAD: H_POWER_MOD,
    PakOp.DARK_HEAL: H_HEAL_HP,
    PakOp.MOMENTUM: H_POWER_MOD,
}


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
    if h in (H_STAT_BUFF, H_STAT_DEBUFF, H_SELF_DEBUFF):
        p = (base_ids + [0, 0, 0, 0])[:4]
        return (p[0], p[1], p[2], p[3])

    # Default: pass through buff_base_ids as params
    p = (base_ids + [0, 0, 0, 0])[:4]
    return (p[0], p[1], p[2], p[3])


# Specific buff_base_id -> mark handler mapping for game mark buffs.
_BUFF_BASE_MARK_MAP: dict[int, int] = {
    2032007: H_MOISTURE_MARK,  # 湿润印记
    2021004: H_WIND_MARK,      # 风起印记
    2143001: H_MOISTURE_MARK,  # MARK_CHANGE family moisture
    2094001: H_METEOR_MARK,    # MARK_METEOR family
}

# Specific buff name patterns -> handler
_BUFF_NAME_MARK_MAP: dict[str, int] = {
    "湿润印记": H_MOISTURE_MARK,
    "风起印记": H_WIND_MARK,
    "龙之印记": H_DRAGON_MARK,
    "蓄力印记": H_CHARGE_MARK,
    "日照印记": H_SOLAR_MARK,
    "攻击印记": H_ATTACK_MARK,
    "迟缓印记": H_SLOW_MARK,
    "精神印记": H_SPIRIT_MARK,
    "陨星印记": H_METEOR_MARK,
    "荆棘印记": H_THORN_MARK,
    "气势印记": H_MOMENTUM_MARK,
    "奉献连击": H_HIT_COUNT,
}


def _classify_buff_handler(buff_id: int, buff_conf: dict[int, dict]) -> int:
    """Classify a BUFF_CONF record into a handler index.

    Priority: exact base_id match > name pattern match > text heuristics >
    PakOp prefix family fallback.
    """
    rec = buff_conf.get(buff_id)
    if rec is None:
        return H_NOOP

    # 1. Check for exact buff_base_id -> mark handler mapping
    base_ids = rec.get("buff_base_ids") or []
    for bid in base_ids:
        if bid and bid in _BUFF_BASE_MARK_MAP:
            return _BUFF_BASE_MARK_MAP[bid]

    # 2. Check buff name for known mark patterns
    import re
    name = rec.get("editor_name", "") or ""
    for pattern, handler in _BUFF_NAME_MARK_MAP.items():
        if pattern in name:
            return handler

    desc = re.sub(r"<[^>]+>", "", rec.get("desc", "") or "")
    t = f"{name} {desc}"

    # 3. Text-based heuristics for status effects and basic handlers
    if "中毒" in t: return H_POISON
    if "灼烧" in t or "焚烧" in t: return H_BURN
    if "冰冻" in t or "冻结" in t: return H_FREEZE
    if "寄生" in t: return H_LEECH
    if "吸血" in t or "吸取" in t: return H_LIFE_DRAIN
    if "减伤" in t or "护盾" in t: return H_DAMAGE_REDUCE
    if any(kw in t for kw in ["物攻", "魔攻", "物防", "魔防", "速度", "双攻", "双防", "全属性"]):
        if any(kw in t for kw in ["降低", "削减", "减少", "减速"]): return H_STAT_DEBUFF
        return H_STAT_BUFF
    if ("回复" in t or "恢复" in t) and "能量" in t: return H_HEAL_ENERGY
    if "回复" in t or "恢复" in t or "治疗" in t: return H_HEAL_HP
    if "威力" in t: return H_POWER_MOD
    if "能耗" in t:
        return H_COST_UP if ("+" in t or "增加" in t) else H_COST_REDUCE
    if "连击" in t: return H_HIT_COUNT
    if "萌化" in t: return H_CUTE_GAIN
    if "吹飞" in t or "换宠" in t: return H_FORCE_SWITCH
    if "驱散" in t or "净化" in t: return H_CLEANSE

    # 4. Fallback: use buff_base_id prefix family -> handler mapping
    for bid in base_ids:
        if bid:
            prefix = bid // 1000
            h = _PAKOP_HANDLER_MAP.get(prefix, H_NOOP)
            if h != H_NOOP:
                return h
    return H_NOOP


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
        return [(PakOp.UNSUPPORTED, effect_id, etype, 0, 0)]


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
