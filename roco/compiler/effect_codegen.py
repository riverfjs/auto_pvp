"""
Data-driven effect code generation from pak game tables.

Replaces the old regex-based classification pipeline with structured lookups
against three core pak tables:

  SKILL_CONF.skill_result[]  -- per-skill chain of effect references
  EFFECT_CONF                -- 956 complex effect definitions (type 1/2/3)
  BUFF_CONF                  -- 1925 buff/debuff definitions with buff_base_ids

Data flow:
  1. build_buff_base_map() scans all BUFF_CONF records, groups by buff_base_id,
     and auto-classifies each base_id via keyword matching on editor_name/desc.
  2. generate_skill_effects() / generate_ability_effects() walk the skill_result
     chain, resolve each entry through EFFECT_CONF or BUFF_CONF, and emit a flat
     list of effect spec dicts.
  3. _decode_effect() handles EFFECT_CONF dispatch (type 1=buff, 2=damage, 3=dispel).
  4. _decode_buff() handles BUFF_CONF lookup via buff_base_ids.

cast_moment values from pak data define when effects trigger during a turn.
They are mapped to the engine's Timing enum via CAST_MOMENT_TO_TIMING.

All classification uses keyword substring matching on Chinese editor_name/desc
strings -- no regex, no manual override files.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from roco.compiler.effect_model import EffectTag, Timing

# ---------------------------------------------------------------------------
# 1. cast_moment -> Timing mapping
# ---------------------------------------------------------------------------
# Derived from frequency analysis of pak SKILL_CONF.skill_result entries:
#   moment  6 (318 refs) : pre-attack setup (power boost, hit count, cleanse)
#   moment  7  (64 refs) : post-hit check (dispel, damage reduction)
#   moment  9   (4 refs) : rare special triggers (faint-related)
#   moment 10  (70 refs) : turn/battle start (energy gain, leader form, buffs)
#   moment 11 (1285 refs): main post-attack effect resolution
#   moment 12  (84 refs) : turn end (transform, persistent stat changes)
#   moment 23  (11 refs) : passive persistent effects
#   moment 24  (29 refs) : switch-in effects
#   moment 25   (9 refs) : charge/prep (蓄力)
#   moment 26  (18 refs) : passive conditional triggers
#   moment 27   (6 refs) : entry aura effects

CAST_MOMENT_TO_TIMING: dict[int, int] = {
    6: Timing.CALC_DAMAGE,    # pre-attack: power/hit setup
    7: Timing.CHECK_HIT,      # post-hit: dispel, reduction
    9: Timing.FAINT,          # special triggers
    10: Timing.TURN_START,    # turn start: energy, leader form
    11: Timing.AFTER_MOVE,    # main effect resolution
    12: Timing.TURN_END,      # end turn: transform, persistent
    23: Timing.PASSIVE,       # passive persistent
    24: Timing.SWITCH_IN,     # switch-in effects
    25: Timing.BEFORE_MOVE,   # charge/prep
    26: Timing.PASSIVE,       # passive conditional
    27: Timing.BATTLE_START,  # entry aura
}

# Default timing when cast_moment is missing or unrecognised.
_DEFAULT_TIMING = Timing.AFTER_MOVE

# ---------------------------------------------------------------------------
# 2. buff_base_id -> EffectTag auto-derivation
# ---------------------------------------------------------------------------
# Keyword rules applied to aggregated editor_name/desc strings for each
# buff_base_id.  Order matters: first match wins.  Each rule is
# (keywords, anti_keywords, tag, params) where *all* keywords must appear
# as substrings and *none* of the anti_keywords may appear.

import re as _re

_STAT_NAMES: dict[str, str] = {
    "物攻": "atk_phys", "物理攻击": "atk_phys",
    "魔攻": "atk_mag", "特殊攻击": "atk_mag", "特攻": "atk_mag",
    "物防": "def_phys", "物理防御": "def_phys",
    "魔防": "def_mag", "特殊防御": "def_mag", "特防": "def_mag",
    "速度": "speed",
    "双攻": "dual_atk", "双防": "dual_def",
}

_STAT_BUFF_RE = _re.compile(r"(物攻|魔攻|物防|魔防|速度|双攻|双防|特攻|特防|物理攻击|特殊攻击|物理防御|特殊防御)\s*[+＋]\s*(\d+)")
_STAT_DEBUFF_RE = _re.compile(r"(物攻|魔攻|物防|魔防|速度|双攻|双防|特攻|特防|物理攻击|特殊攻击|物理防御|特殊防御)\s*[-－]\s*(\d+)")

_SINGLE_KW_RULES: list[tuple[str, EffectTag, dict[str, Any]]] = [
    ("中毒", EffectTag.POISON, {}),
    ("灼烧", EffectTag.BURN, {}),
    ("冰冻", EffectTag.FREEZE, {}),
    ("冻结", EffectTag.FREEZE, {}),
    ("寄生", EffectTag.LEECH, {}),
    ("吸血", EffectTag.LIFE_DRAIN, {}),
    ("吸取", EffectTag.LIFE_DRAIN, {}),
    ("萌化", EffectTag.UNSUPPORTED, {"sub": "cute"}),
    ("印记", EffectTag.UNSUPPORTED, {"sub": "mark"}),
    ("能耗", EffectTag.UNSUPPORTED, {"sub": "cost_mod"}),
    ("威力", EffectTag.UNSUPPORTED, {"sub": "power_mod"}),
    ("连击", EffectTag.UNSUPPORTED, {"sub": "hit_count"}),
    ("减伤", EffectTag.DAMAGE_REDUCTION, {}),
    ("护盾", EffectTag.UNSUPPORTED, {"sub": "shield"}),
    ("驱散", EffectTag.UNSUPPORTED, {"sub": "dispel"}),
    ("净化", EffectTag.UNSUPPORTED, {"sub": "cleanse"}),
    ("禁止更换", EffectTag.UNSUPPORTED, {"sub": "lock_switch"}),
    ("免疫", EffectTag.UNSUPPORTED, {"sub": "immunity"}),
    ("回复", EffectTag.HEAL_HP, {}),
    ("恢复", EffectTag.HEAL_HP, {}),
    ("能量", EffectTag.HEAL_ENERGY, {}),
    ("减速", EffectTag.ENEMY_DEBUFF, {"stat": "speed"}),
]


def _classify_text(text: str) -> tuple[EffectTag, dict[str, Any]]:
    """Classify an effect from its combined editor_name + desc text."""
    buff_m = _STAT_BUFF_RE.search(text)
    if buff_m:
        stat = _STAT_NAMES.get(buff_m.group(1), "")
        return EffectTag.SELF_BUFF, {"stat": stat, "value": int(buff_m.group(2))}

    debuff_m = _STAT_DEBUFF_RE.search(text)
    if debuff_m:
        stat = _STAT_NAMES.get(debuff_m.group(1), "")
        return EffectTag.ENEMY_DEBUFF, {"stat": stat, "value": int(debuff_m.group(2))}

    for kw, tag, params in _SINGLE_KW_RULES:
        if kw in text:
            return tag, dict(params)

    return EffectTag.UNSUPPORTED, {}


def build_buff_base_map(buff_conf: dict[int, dict]) -> dict[int, tuple[EffectTag, dict]]:
    """Classify every unique buff_base_id from BUFF_CONF via keyword matching.

    Parameters
    ----------
    buff_conf : dict[int, dict]
        Mapping of buff_id -> buff record.  Each record is expected to have:
        - ``buff_base_ids``: list[int] of reusable template IDs
        - ``editor_name``: str  (Chinese display name)
        - ``desc``: str         (Chinese description, may be empty)
        - ``type``: int         (1=positive, 3=debuff/special, 4=enhancement)

    Returns
    -------
    dict[int, tuple[EffectTag, dict]]
        Mapping from buff_base_id -> (EffectTag, params_dict).
        Unclassifiable base_ids get ``(EffectTag.UNSUPPORTED, {})``.
    """
    # Phase 1: collect all editor_name/desc strings per base_id.
    base_id_texts: dict[int, list[str]] = defaultdict(list)
    base_id_types: dict[int, set[int]] = defaultdict(set)

    for buff in buff_conf.values():
        base_ids = buff.get("buff_base_ids") or []
        name = buff.get("editor_name", "") or ""
        desc = buff.get("desc", "") or ""
        btype = buff.get("type", 0)
        combined = f"{name} {desc}".strip()
        for bid in base_ids:
            if bid:
                base_id_texts[bid].append(combined)
                base_id_types[bid].add(btype)

    # Phase 2: classify each base_id.
    result: dict[int, tuple[EffectTag, dict]] = {}
    for bid, texts in base_id_texts.items():
        # Strip HTML tags from desc for cleaner matching.
        clean = _re.sub(r"<[^>]+>", "", " ".join(texts))
        tag, params = _classify_text(clean)

        if tag == EffectTag.SELF_BUFF and base_id_types.get(bid) == {3}:
            tag = EffectTag.ENEMY_DEBUFF

        result[bid] = (tag, params)

    return result


# ---------------------------------------------------------------------------
# 3. Core generation functions
# ---------------------------------------------------------------------------

def generate_skill_effects(
    skill_row: dict,
    effect_conf: dict[int, dict],
    buff_conf: dict[int, dict],
    buff_base_map: dict[int, tuple[EffectTag, dict]],
) -> list[dict]:
    """Generate effect spec dicts from a skill's ``skill_result`` chain.

    Parameters
    ----------
    skill_row : dict
        A single SKILL_CONF record with at least ``skill_result`` (list of
        result entries).  Each result entry has:
        - ``effect_id``: int  (references EFFECT_CONF or BUFF_CONF)
        - ``cast_moment``: int
        - ``result_target_type``: int  (1=self, 2=enemy, 3=enemy)
        - ``success_rate``: int  (10000 = 100%)
    effect_conf : dict[int, dict]
        Full EFFECT_CONF table keyed by effect_id.
    buff_conf : dict[int, dict]
        Full BUFF_CONF table keyed by buff_id.
    buff_base_map : dict[int, tuple[EffectTag, dict]]
        Output of :func:`build_buff_base_map`.

    Returns
    -------
    list[dict]
        Each dict has keys: ``tag``, ``timing``, ``target``, ``params``,
        ``sort_order``.
    """
    results: list[dict] = []
    skill_results = skill_row.get("skill_result") or []

    for idx, entry in enumerate(skill_results):
        effect_id = entry.get("effect_id", 0)
        cast_moment = entry.get("cast_moment", 11)
        target_type = entry.get("result_target_type", 1)
        success_rate = entry.get("success_rate", 10000)

        timing = CAST_MOMENT_TO_TIMING.get(cast_moment, _DEFAULT_TIMING)
        target = _resolve_target(target_type)

        # Try EFFECT_CONF first, then BUFF_CONF as direct buff reference.
        if effect_id in effect_conf:
            decoded = _decode_effect(effect_id, effect_conf, buff_conf, buff_base_map)
        elif effect_id in buff_conf:
            decoded = _decode_buff(effect_id, buff_conf, buff_base_map)
        else:
            decoded = [{"tag": EffectTag.UNSUPPORTED, "params": {"effect_id": effect_id}}]

        for d in decoded:
            params = d.get("params", {})
            params["success_rate"] = success_rate
            params["cast_moment"] = cast_moment
            results.append({
                "tag": d["tag"],
                "timing": timing,
                "target": target,
                "params": params,
                "sort_order": idx,
            })

    return results


def generate_ability_effects(
    ability_row: dict,
    effect_conf: dict[int, dict],
    buff_conf: dict[int, dict],
    buff_base_map: dict[int, tuple[EffectTag, dict]],
) -> list[dict]:
    """Generate effect spec dicts for an ability (same structure as skills).

    Abilities use the same ``skill_result`` structure as skills in pak data,
    so this delegates to the same decoding pipeline.

    Parameters
    ----------
    ability_row : dict
        A single ability record.  Expected to have ``skill_result`` or
        ``effect_list`` containing the same entry structure as skills.
    effect_conf, buff_conf, buff_base_map :
        Same as :func:`generate_skill_effects`.

    Returns
    -------
    list[dict]
        Same format as :func:`generate_skill_effects`.
    """
    # Abilities may store their effect chain under different keys.
    if "skill_result" not in ability_row and "effect_list" in ability_row:
        ability_row = dict(ability_row)
        ability_row["skill_result"] = ability_row["effect_list"]

    return generate_skill_effects(ability_row, effect_conf, buff_conf, buff_base_map)


# ---------------------------------------------------------------------------
# 4. _decode_effect -- EFFECT_CONF dispatcher
# ---------------------------------------------------------------------------

def _decode_effect(
    effect_id: int,
    effect_conf: dict[int, dict],
    buff_conf: dict[int, dict],
    buff_base_map: dict[int, tuple[EffectTag, dict]],
) -> list[dict]:
    """Decode an EFFECT_CONF entry into one or more (tag, params) pairs.

    EFFECT_CONF type dispatch:
      type=1 : buff application.  ``effect_param`` contains a buff_id that
               references BUFF_CONF.
      type=2 : damage effect.  Param positions:
               [0] = mode (0=fixed, 1=percent, etc.)
               [2] = power or percent value
               [6] = self-damage percent (recoil)
      type=3 : state change / dispel.  ``effect_param[1]`` contains a list
               of buff_ids to remove from the target.

    Falls back to editor_name keyword matching when structured params are
    ambiguous.
    """
    rec = effect_conf.get(effect_id)
    if rec is None:
        return [{"tag": EffectTag.UNSUPPORTED, "params": {"effect_id": effect_id}}]

    etype = rec.get("type", 0)
    params_raw = rec.get("effect_param") or rec.get("params") or []
    editor_name = rec.get("editor_name", "") or ""
    desc = rec.get("desc", "") or ""
    combined_text = f"{editor_name} {desc}".strip()

    if etype == 1:
        return _decode_effect_type1_buff(params_raw, buff_conf, buff_base_map, combined_text)
    elif etype == 2:
        return _decode_effect_type2_damage(params_raw, combined_text)
    elif etype == 3:
        return _decode_effect_type3_dispel(params_raw, combined_text)
    else:
        # Unknown effect type -- try keyword fallback.
        tag, kw_params = _match_keywords(combined_text, _KW_RULES)
        kw_params["effect_id"] = effect_id
        kw_params["effect_type"] = etype
        return [{"tag": tag, "params": kw_params}]


def _decode_effect_type1_buff(
    params_raw: list,
    buff_conf: dict[int, dict],
    buff_base_map: dict[int, tuple[EffectTag, dict]],
    text: str,
) -> list[dict]:
    """Type 1: buff application.  Extract buff_id from params and resolve."""
    buff_id = _safe_int(params_raw, 0)
    if buff_id and buff_id in buff_conf:
        return _decode_buff(buff_id, buff_conf, buff_base_map)

    # Try second param position as fallback.
    buff_id = _safe_int(params_raw, 1)
    if buff_id and buff_id in buff_conf:
        return _decode_buff(buff_id, buff_conf, buff_base_map)

    # Fall back to keyword matching on editor text.
    tag, kw_params = _classify_text(text)
    kw_params["raw_params"] = params_raw[:4] if len(params_raw) >= 4 else list(params_raw)
    return [{"tag": tag, "params": kw_params}]


def _decode_effect_type2_damage(params_raw: list, text: str) -> list[dict]:
    """Type 2: damage effect.

    Param layout (from pak data analysis):
      [0] = mode        (0=fixed damage, 1=percent of max HP, 2=percent of current HP)
      [2] = power/pct   (damage value or percentage * 100)
      [6] = self_damage  (recoil percent * 100, 0 if none)
    """
    mode = _safe_int(params_raw, 0)
    power = _safe_int(params_raw, 2)
    self_damage = _safe_int(params_raw, 6)

    results: list[dict] = []

    # Main damage.
    damage_params: dict[str, Any] = {"mode": mode, "power": power}
    tag = EffectTag.DAMAGE

    # Check for life drain via text.
    if "吸血" in text or "吸取" in text:
        tag = EffectTag.LIFE_DRAIN
        damage_params["drain"] = True

    results.append({"tag": tag, "params": damage_params})

    # Self-damage (recoil) as a separate effect entry.
    if self_damage and self_damage > 0:
        results.append({
            "tag": EffectTag.SELF_DEBUFF,
            "params": {"sub": "recoil", "pct": self_damage},
        })

    return results


def _decode_effect_type3_dispel(params_raw: list, text: str) -> list[dict]:
    """Type 3: state change / dispel.

    ``params_raw[1]`` may contain a buff_id or list of buff_ids to remove.
    """
    remove_ids = _extract_id_list(params_raw, 1)
    params: dict[str, Any] = {}

    if remove_ids:
        params["remove_buff_ids"] = remove_ids

    # Classify by text.
    if "驱散" in text:
        params["sub"] = "dispel"
    elif "净化" in text:
        params["sub"] = "cleanse"
    elif "解除" in text:
        params["sub"] = "remove_status"
    else:
        tag, kw_params = _classify_text(text)
        if tag != EffectTag.UNSUPPORTED:
            kw_params.update(params)
            return [{"tag": tag, "params": kw_params}]

    # Use UNSUPPORTED with sub-classification for now; parse_pak.py will
    # map these to concrete tags once the full tag set stabilises.
    return [{"tag": EffectTag.UNSUPPORTED, "params": params}]


# ---------------------------------------------------------------------------
# 5. _decode_buff -- BUFF_CONF lookup via buff_base_ids
# ---------------------------------------------------------------------------

def _decode_buff(
    buff_id: int,
    buff_conf: dict[int, dict],
    buff_base_map: dict[int, tuple[EffectTag, dict]],
) -> list[dict]:
    """Decode a BUFF_CONF entry into effect specs.

    Classification priority:
    1. Classify the buff record's own editor_name + desc directly
    2. If that yields UNSUPPORTED, try buff_base_ids via buff_base_map
    """
    rec = buff_conf.get(buff_id)
    if rec is None:
        return [{"tag": EffectTag.UNSUPPORTED, "params": {"buff_id": buff_id}}]

    editor_name = rec.get("editor_name", "") or ""
    desc = _re.sub(r"<[^>]+>", "", rec.get("desc", "") or "")
    btype = rec.get("type", 0)
    add_max = rec.get("add_max", 1)
    combined = f"{editor_name} {desc}".strip()

    tag, params = _classify_text(combined)
    params["buff_id"] = buff_id
    params["buff_type"] = btype
    if add_max and add_max != 1:
        params["add_max"] = add_max

    if tag != EffectTag.UNSUPPORTED:
        if btype in (2, 3) and tag == EffectTag.SELF_BUFF:
            tag = EffectTag.ENEMY_DEBUFF
        return [{"tag": tag, "params": params}]

    base_ids = [bid for bid in (rec.get("buff_base_ids") or []) if bid]
    if not base_ids:
        return [{"tag": EffectTag.UNSUPPORTED, "params": params}]

    results: list[dict] = []
    for bid in base_ids:
        btag, bparams = buff_base_map.get(bid, (EffectTag.UNSUPPORTED, {}))
        bparams = dict(bparams)
        bparams["buff_id"] = buff_id
        bparams["buff_base_id"] = bid
        bparams["buff_type"] = btype
        if btype in (2, 3) and btag == EffectTag.SELF_BUFF:
            btag = EffectTag.ENEMY_DEBUFF
        results.append({"tag": btag, "params": bparams})

    return results if results else [{"tag": EffectTag.UNSUPPORTED, "params": params}]


# ---------------------------------------------------------------------------
# 6. Gap reporting
# ---------------------------------------------------------------------------

def report_gaps(buff_base_map: dict[int, tuple[EffectTag, dict]]) -> dict:
    """Return statistics on unmapped / partially mapped effects.

    Returns
    -------
    dict
        ``total``           : total buff_base_ids in the map
        ``classified``      : count with tag != UNSUPPORTED
        ``unsupported``     : count with tag == UNSUPPORTED
        ``coverage_pct``    : classification coverage as a float 0-100
        ``unsupported_ids`` : list of unclassified buff_base_ids
        ``tag_distribution``: dict[str, int] tag name -> count
    """
    total = len(buff_base_map)
    unsupported_ids: list[int] = []
    tag_counts: dict[str, int] = defaultdict(int)

    for bid, (tag, _params) in buff_base_map.items():
        tag_name = tag.name if hasattr(tag, "name") else str(tag)
        tag_counts[tag_name] += 1
        if tag == EffectTag.UNSUPPORTED:
            unsupported_ids.append(bid)

    classified = total - len(unsupported_ids)
    coverage = (classified / total * 100.0) if total > 0 else 0.0

    return {
        "total": total,
        "classified": classified,
        "unsupported": len(unsupported_ids),
        "coverage_pct": round(coverage, 2),
        "unsupported_ids": sorted(unsupported_ids),
        "tag_distribution": dict(sorted(tag_counts.items(), key=lambda kv: -kv[1])),
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _resolve_target(target_type: int) -> str:
    """Map pak result_target_type to a semantic target string.

    Known values:
      1 = self
      2 = enemy (single)
      3 = enemy (all / AoE)
    """
    if target_type == 1:
        return "self"
    elif target_type in (2, 3):
        return "enemy"
    else:
        return "unknown"


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
    """Safely extract an int from a pak effect_param list by index."""
    val = _unwrap_param(lst, index)
    if val is None:
        return default
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def _extract_id_list(lst: list, index: int) -> list[int]:
    """Extract a single int or a list of ints from a param position.

    pak data sometimes stores a single ID and sometimes a sub-list at
    a given param position.
    """
    val = _unwrap_param(lst, index)
    if val is None:
        return []
    if isinstance(val, list):
        return [int(v) for v in val if v]
    if isinstance(val, (int, float)) and val:
        return [int(val)]
    return []
