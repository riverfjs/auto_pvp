"""Compile SQLite catalog rows into hot/debug Python artifacts for the fixed kernel."""

from __future__ import annotations

import argparse
import json
import pprint
import sqlite3
from pathlib import Path
from typing import Any

from roco.data.utils import DB_DIR, ROOT, content_hash
from roco.compiler.effect_model import PakOp
from roco.common.enums import AbilityFlag, Element, SkillCategory, WeatherType
from roco.common.packing import _add_buff_bps
from roco.common.constants import BPS, HP_FOR_ENERGY_PCT_BPS
from roco.engine.kernel.ops import KERNEL_SUPPORTED_TAGS
from roco.compiler.type_chart import effectiveness_v2

CATALOG_VERSION = 1
SCHEMA_VERSION = "kernel-v1"
HOT_PATH = ROOT / "roco" / "engine" / "generated" / "catalog_hot.py"
DEBUG_PATH = ROOT / "roco" / "engine" / "generated" / "catalog_debug.py"

TARGET_CODES = {
    "": 0,
    "self": 1,
    "enemy": 2,
    "ally": 3,
    "team": 4,
    "enemy_team": 5,
}
COND_CODES = {"": 0, "counter": 1, "counter_status": 2, "status": 2, "not_blocked": 3}
KERNEL_SUPPORTED_TAG_SET = frozenset(KERNEL_SUPPORTED_TAGS)
WEATHER_CODES = {
    "rain": WeatherType.RAIN.value,
    "sandstorm": WeatherType.SANDSTORM.value,
    "snow": WeatherType.SNOW.value,
    "hail": WeatherType.SNOW.value,
}
ABILITY_FLAG_TAGS: dict[int, AbilityFlag] = {}


def _connect(path: Path | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path or DB_DIR / "data.db"))
    conn.row_factory = sqlite3.Row
    return conn


def _rows(conn: sqlite3.Connection, sql: str) -> list[sqlite3.Row]:
    return list(conn.execute(sql))


def _source_payload(conn: sqlite3.Connection) -> dict[str, Any]:
    return {
        "elements": [tuple(row) for row in _rows(conn, "SELECT id, code, name FROM elements ORDER BY id")],
        "pets": [tuple(row) for row in _rows(conn, "SELECT id, name, lineage_key, form_type, element_primary_id, element_secondary_id, ability_id, hp, atk_phys, atk_mag, def_phys, def_mag, speed FROM pets ORDER BY id")],
        "pet_transforms": [tuple(row) for row in _rows(conn, "SELECT source_pet_id, leader_pet_id, reason FROM pet_transforms ORDER BY source_pet_id")],
        "skills": [tuple(row) for row in _rows(conn, "SELECT id, name, element_id, category_code, energy, power, flags FROM skills ORDER BY id")],
        "pet_skills": [tuple(row) for row in _rows(conn, "SELECT pet_id, skill_id, sort_order FROM pet_skills WHERE skill_id IS NOT NULL ORDER BY pet_id, sort_order, id")],
        "skill_effects": [tuple(row) for row in _rows(conn, "SELECT skill_id, timing_code, tag_code, flags, params_json, condition, sort_order FROM skill_effects ORDER BY skill_id, sort_order, id")],
        "ability_effects": [tuple(row) for row in _rows(conn, "SELECT ability_id, timing_code, tag_code, flags, params_json, condition, sort_order FROM ability_effects ORDER BY ability_id, sort_order, id")],
        "bloodlines": [tuple(row) for row in _rows(conn, "SELECT id, code, name, kind, element_id FROM bloodlines ORDER BY id")],
        "bloodline_magics": [tuple(row) for row in _rows(conn, "SELECT id, code, name, uses_per_battle FROM bloodline_magics ORDER BY id")],
    }


def _type_chart_bps(element_names: tuple[str, ...]) -> tuple[tuple[int, ...], ...]:
    rows: list[tuple[int, ...]] = []
    for move in element_names:
        rows.append(tuple(int(effectiveness_v2(move, (defender,)) * 10000) for defender in element_names))
    return tuple(rows)


def _effect_args(tag: int, params: dict[str, Any], skill_ids: dict[str, int] | None = None) -> tuple[int, int, int, int]:
    T = PakOp
    result = _status_and_weather_args(tag, params, T)
    if result is not None:
        return result
    result = _damage_and_combat_args(tag, params, T, skill_ids)
    if result is not None:
        return result
    result = _buff_and_cost_args(tag, params, T)
    if result is not None:
        return result
    result = _element_conditional_args(tag, params, T)
    if result is not None:
        return result
    result = _cute_args(tag, params, T)
    if result is not None:
        return result
    result = _misc_args(tag, params, T)
    if result is not None:
        return result
    return _fallback_args(params)


_Args = tuple[int, int, int, int] | None


def _status_and_weather_args(tag: int, p: dict[str, Any], T: type) -> _Args:
    if tag in {T.BURN.value, T.POISON.value, T.FREEZE.value, T.LEECH.value}:
        return (int(p.get("stacks", 0) or 0), 0, 0, 0)
    if tag == T.WEATHER.value:
        weather = WEATHER_CODES.get(str(p.get("type", "")), 0)
        turns = max(1, min(15, int(p.get("turns", 5) or 5))) if weather else 0
        return (weather, turns, 0, 0)
    return None


def _damage_and_combat_args(tag: int, p: dict[str, Any], T: type, skill_ids: dict[str, int] | None) -> _Args:
    if tag == T.DAMAGE.value:
        return (int(p.get("power", 0) or 0), int(p.get("hit_count", 1) or 1), 0, 0)
    if tag == T.DAMAGE_REDUCTION.value:
        return (max(0, BPS - int(float(p.get("pct", 0) or 0) * BPS)), 0, 0, 0)
    if tag == T.LIFE_DRAIN.value:
        return (int(float(p.get("pct", 0) or 0) * BPS), 0, 0, 0)
    if tag == T.CONSUME_MARKS_HEAL.value:
        return (int(float(p.get("pct", p.get("heal_pct", 0.1)) or 0) * BPS), 0, 0, 0)
    if tag == T.POWER_DYNAMIC.value:
        return (int(float(p.get("multiplier", 0) or 0) * BPS), int(p.get("bonus", 0) or 0), 0, 0)
    if tag == T.PERMANENT_MOD.value:
        target = {"cost": 1, "power": 2, "hit_count": 3}.get(str(p.get("target", "")), 0)
        return (target, int(p.get("delta", 0) or 0), 0, 0)
    if tag == T.NEXT_ATTACK_MOD.value:
        return (int(p.get("power_bonus", 0) or 0), 0, 0, 0)
    if tag in {T.FIRST_STRIKE_POWER_BONUS.value, T.POWER_MULTIPLIER_BUFF.value}:
        pct = p.get("bonus_pct")
        if pct is not None:
            return (BPS + int(float(pct) * BPS), 0, 0, 0)
    if tag in {T.FIRST_STRIKE_HIT_COUNT.value, T.HIT_COUNT_PER_POISON.value}:
        return (int(p.get("amount", p.get("hits", p.get("per", 1))) or 1), 0, 0, 0)
    if tag == T.STAT_SCALE_HITS_PER_HP_LOST.value:
        return (int(p.get("amount", p.get("hits", 1)) or 1), 0, 0, 0)
    if tag == T.HIT_COUNT_DELTA.value:
        return (int(p.get("delta", p.get("amount", 0)) or 0), 0, 0, 0)
    if tag == T.COUNTER_ATTACK.value:
        return (int(p.get("power", 50) or 50), 0, 0, 0)
    if tag == T.ANTI_HEAL.value:
        return (int(p.get("multiplier", 2) or 2), 0, 0, 0)
    if tag in {T.DAMAGE_MOD_NON_STAB.value, T.DAMAGE_MOD_NON_LIGHT.value, T.DAMAGE_MOD_NON_WEAKNESS.value, T.DAMAGE_MOD_POLLUTANT_BLOOD.value, T.DAMAGE_MOD_LEADER_BLOOD.value}:
        return (_bonus_bps(p, default=0.5), 0, 0, 0)
    if tag == T.LOW_COST_SKILL_POWER_BONUS.value:
        return (int(p.get("cost_threshold", p.get("value", 1)) or 1), _bonus_bps(p, default=0.5), 0, 0)
    if tag == T.POWER_BY_STATUS_COUNT_ELEMENTS.value:
        mask = 0
        raw = p.get("elements", ())
        if isinstance(raw, str):
            raw = [raw]
        if isinstance(raw, list):
            for element in raw:
                idx = _element_id_param({"element": element})
                if idx >= 0:
                    mask |= 1 << idx
        return (mask, int(p.get("power_bonus", p.get("bonus", 0)) or 0), 0, 0)
    if tag == T.SKILL_MOD.value:
        return (_slot_mask_param(p), int(p.get("priority", 0) or 0), int(p.get("power_bonus", p.get("bonus", 0)) or 0), int(p.get("hit_delta", p.get("drive", 0)) or 0))
    if tag == T.SPECIFIC_SKILL_POWER_BONUS.value:
        skill_id = int(p.get("skill_id", 0) or 0)
        if skill_id <= 0 and skill_ids is not None:
            skill_id = skill_ids.get(str(p.get("skill", "")).strip(), 0)
        return (skill_id, int(p.get("power_bonus", p.get("bonus", 0)) or 0), 0, 0)
    if tag == T.TEAM_SYNERGY_BUG_SWARM_ATTACK.value:
        return (int(float(p.get("bonus_pct", p.get("pct", 0.15)) or 0.15) * BPS), 0, 0, 0)
    if tag == T.CARRY_SKILL_POWER_BONUS.value:
        condition = {"": 0, "cost_eq": 1, "cost_gt": 2, "cost_le": 3, "cost_lte": 3}.get(str(p.get("condition", "")), 0)
        return (condition, int(p.get("value", p.get("cost_threshold", 0)) or 0), _bonus_bps(p, default=0.4), 0)
    if tag == T.COUNTER_ACCUMULATE_TRANSFORM.value:
        category = {"attack": 1, "攻击": 1, "status": 2, "defense": 2, "防御": 2, "状态": 2}.get(str(p.get("category", "")), 0)
        return (int(p.get("count", p.get("required", 1)) or 1), category, int(bool(p.get("heal_full", True))), 0)
    return None


def _buff_and_cost_args(tag: int, p: dict[str, Any], T: type) -> _Args:
    if tag in {T.SELF_BUFF.value, T.SELF_DEBUFF.value, T.ENEMY_DEBUFF.value}:
        return (_pack_buff_params(p), 0, 0, 0)
    if tag == T.ON_SUPER_EFFECTIVE_BUFF.value:
        return (_pack_buff_params(p.get("buff", {}) if isinstance(p.get("buff"), dict) else p), int(p.get("energy", p.get("amount", 0)) or 0), 0, 0)
    if tag == T.DEBUFF_EXTRA_LAYERS.value:
        return (int(p.get("layers", p.get("amount", 0)) or 0) * 1000, 0, 0, 0)
    if tag == T.HP_FOR_ENERGY.value:
        pct = p.get("pct")
        return (int(float(pct) * BPS) if pct is not None else HP_FOR_ENERGY_PCT_BPS, 0, 0, 0)
    if tag == T.ENEMY_ENERGY_COST_UP.value:
        return (int(p.get("amount", 0) or 0), int(p.get("turns", 0) or 0), _cost_scope_param(p), _cost_trigger_param(p))
    if tag == T.ENEMY_ALL_COST_UP.value:
        return (int(p.get("amount", 0) or 0), int(p.get("turns", 15) or 15), 1, 0)
    if tag == T.PASSIVE_ENERGY_REDUCE.value:
        return (int(p.get("amount", p.get("reduce", 0)) or 0), 0, 0, 0)
    if tag == T.CHARGE_COST_REDUCE.value:
        return (int(p.get("reduce", p.get("amount", 0)) or 0), 0, 0, 0)
    if tag in {T.CARRY_SKILL_COST_REDUCE.value, T.SKILL_COST_REDUCTION_TYPE.value}:
        category = {"physical": 1, "magical": 2, "attack": 1, "defense": 3, "status": 4, "防御": 3, "状态": 4}.get(str(p.get("category", "")), 0)
        return (category, int(p.get("reduce", p.get("cost_reduction", 0)) or 0), 0, 0)
    if tag in {T.ENERGY_REGEN_PER_TURN.value, T.LEAVE_ENERGY_REFILL.value, T.STEAL_ALL_ENEMY_ENERGY.value}:
        return (int(p.get("amount", 0) or 0), 0, 0, 0)
    if tag == T.ENEMY_SWITCH_SELF_COST_REDUCE.value:
        return (int(p.get("reduce", p.get("amount", 0)) or 0), 0, 0, 0)
    return None


def _element_conditional_args(tag: int, p: dict[str, Any], T: type) -> _Args:
    if tag == T.ON_SKILL_ELEMENT_BUFF.value:
        return (_element_id_param(p), _pack_buff_params(p.get("buff", {}) if isinstance(p.get("buff"), dict) else p), 0, 0)
    if tag in {T.ON_SKILL_ELEMENT_POISON.value, T.ON_SKILL_ELEMENT_BURN.value, T.ON_SKILL_ELEMENT_FREEZE.value}:
        return (_element_id_param(p), int(p.get("stacks", 1) or 1), 0, 0)
    if tag == T.ON_SKILL_ELEMENT_HIT_COUNT.value:
        return (_element_id_param(p), int(p.get("amount", p.get("hits", 1)) or 1), 0, 0)
    if tag == T.ON_SKILL_ELEMENT_COST_REDUCE.value:
        return (_element_id_param(p), int(p.get("reduce", 0) or 0), 0, 0)
    if tag == T.ON_SKILL_ELEMENT_ENEMY_ENERGY.value:
        return (_element_id_param(p), int(p.get("amount", 0) or 0), 0, 0)
    if tag == T.ENTRY_ENERGY_FROM_ELEMENT_COUNT.value:
        return (_element_id_param(p), int(p.get("amount", p.get("energy", 0)) or 0), 0, 0)
    if tag == T.ENTRY_ENERGY_FROM_COUNTER_COUNT.value:
        return (int(p.get("amount", p.get("energy", 0)) or 0), 0, 0, 0)
    if tag == T.ENTRY_BUFF_PER_SKILL_COUNT.value:
        mode = {"cost": 1, "power": 2}.get(str(p.get("mode", "")), 0)
        return (_element_id_param(p), mode, int(p.get("amount", p.get("delta", 0)) or 0), 0)
    if tag == T.HEAL_ON_GRASS_SKILL.value:
        return (int(float(p.get("heal_pct", p.get("pct", 0.1)) or 0.1) * BPS), 0, 0, 0)
    if tag == T.POISON_ON_SKILL_APPLY.value:
        return (int(p.get("cost_threshold", p.get("threshold", 1)) or 1), int(p.get("stacks", 1) or 1), 0, 0)
    if tag == T.BLOODLINE_ENTRY.value:
        return (_element_id_param(p), _pack_buff_params({"atk": -0.6, "spatk": -0.6}), 0, 0)
    return None


def _cute_args(tag: int, p: dict[str, Any], T: type) -> _Args:
    if tag in {T.CUTE_GAIN.value, T.CUTE_ENEMY_GAIN.value, T.CUTE_BOTH.value, T.CUTE_LETHAL_SHIELD.value}:
        return (int(p.get("stacks", 1) or 1), 0, 0, 0)
    if tag == T.CUTE_IF_POWER_BONUS.value:
        return (int(p.get("bonus", 0) or 0), 0, 0, 0)
    if tag == T.CUTE_ON_GAIN_POWER_PERM.value:
        return (int(p.get("stacks", 1) or 1), int(p.get("delta", 0) or 0), 0, 0)
    if tag == T.CUTE_ON_GAIN_COST_REDUCE.value:
        return (int(p.get("stacks", 1) or 1), int(p.get("reduce", 0) or 0), 0, 0)
    if tag == T.CUTE_ON_GAIN_SPEED_PERM.value:
        speed = float(p.get("speed", 0) or 0)
        return (int(p.get("stacks", 1) or 1), _pack_buff_params({"speed": speed / 100.0}), 0, 0)
    if tag in {T.CUTE_TEAM_POWER.value, T.CUTE_HIT_PER_STACK.value}:
        return (int(p.get("per", p.get("hits", 1)) or 1), 0, 0, 0)
    if tag == T.CUTE_BENCH_COST_REDUCE.value:
        return (int(p.get("reduce", p.get("amount", 1)) or 1), 0, 0, 0)
    return None


def _misc_args(tag: int, p: dict[str, Any], T: type) -> _Args:
    if tag == T.COUNTER_SUCCESS_SPEED_PRIORITY.value:
        return (int(p.get("priority", p.get("amount", 1)) or 1), 0, 0, 0)
    if tag == T.ENTRY_SELF_DAMAGE.value:
        return (int(float(p.get("pct_current", p.get("pct", 0.5)) or 0) * BPS), 0, 0, 0)
    if tag == T.GRANT_LIFE_DRAIN.value:
        return (int(float(p.get("pct", 0.5) or 0) * BPS), 0, 0, 0)
    if tag == T.CONTRACT_ENTRY.value:
        return (_pack_buff_params({"speed": float(p.get("speed", 0.5) or 0.5)}), int(p.get("poison", 1) or 1), 0, 0)
    if tag == T.ON_INTERRUPT_COOLDOWN.value:
        return (int(p.get("turns", 2) or 2), 0, 0, 0)
    if tag == T.LEAVE_HEAL_ALLY.value:
        return (int(float(p.get("pct", 0.0) or 0.0) * BPS), 0, 0, 0)
    if tag == T.DEVOTION_GRANT_RANDOM.value:
        return (int(p.get("amount", p.get("count", 1)) or 1), 0, 0, 0)
    if tag in {T.MIRROR_ENEMY_BUFFS.value, T.CONVERT_POISON_TO_MARK.value, T.ENERGY_DRAIN_BY_COST_DIFF.value, T.EXCHANGE_MOVES.value, T.EXCHANGE_HP_RATIO.value, T.BORROW_TEAM_SKILL.value, T.TRANSFER_MODS.value}:
        return (0, 0, 0, 0)
    return None


def _fallback_args(p: dict[str, Any]) -> tuple[int, int, int, int]:
    pct = p.get("pct")
    if pct is not None:
        return (int(float(pct) * 10000), 0, 0, 0)
    stacks = p.get("stacks")
    if stacks is not None:
        return (int(stacks), 0, 0, 0)
    amount = p.get("amount")
    if amount is not None:
        return (int(amount), 0, 0, 0)
    return (0, 0, 0, 0)


def _pack_buff_params(params: dict[str, Any]) -> int:
    stat_index = {"atk": 0, "spatk": 1, "def": 2, "spdef": 3, "speed": 4}
    packed = 0
    for key, idx in stat_index.items():
        value = float(params.get(key, 0) or 0)
        if value:
            packed = _add_buff_bps(packed, idx, int(value * BPS))
    return packed


def _bonus_bps(params: dict[str, Any], *, default: float) -> int:
    bonus = params.get("bonus_pct", params.get("pct", default))
    return BPS + int(float(bonus or 0) * BPS)


def _element_id_param(params: dict[str, Any]) -> int:
    raw = str(params.get("element", "") or params.get("target_element", "") or "")
    if not raw:
        return 0
    return Element.from_str(raw).value


def _slot_mask_param(params: dict[str, Any]) -> int:
    raw = params.get("slots", params.get("slot", ()))
    if isinstance(raw, int):
        values = (raw,)
    elif isinstance(raw, (list, tuple)):
        values = tuple(raw)
    else:
        values = (raw,)
    mask = 0
    for value in values:
        try:
            idx = int(value)
        except (TypeError, ValueError):
            continue
        if 0 <= idx < 4:
            mask |= 1 << idx
        elif 1 <= idx <= 4:
            mask |= 1 << (idx - 1)
    return mask


def _cost_scope_param(params: dict[str, Any]) -> int:
    scope = str(params.get("scope", "all"))
    return {
        "all": 1,
        "current_skill": 2,
        "current": 2,
        "other_skills": 3,
        "other": 3,
        "attack": 4,
    }.get(scope, 1)


def _cost_trigger_param(params: dict[str, Any]) -> int:
    trigger = str(params.get("trigger", ""))
    required = str(params.get("requires_skill_category", ""))
    if trigger == "inflict_freeze":
        return 1
    if required in {"status", "状态"}:
        return 2
    if required in {"attack", "攻击"}:
        return 3
    return 0


def _effect_row(row: sqlite3.Row, skill_ids: dict[str, int] | None = None) -> tuple[int, int, int, int, int, int, int, int, int]:
    params = json.loads(row["params_json"] or "{}")
    target = TARGET_CODES.get(str(params.get("target", "")), 0)
    condition = str(row["condition"] or params.get("condition", ""))
    cond_code = COND_CODES.get(condition, -1)
    arg0, arg1, arg2, arg3 = _effect_args(int(row["tag_code"]), params, skill_ids)
    return (
        int(row["tag_code"]),
        int(row["timing_code"]),
        target,
        int(row["flags"]),
        cond_code,
        arg0,
        arg1,
        arg2,
        arg3,
    )


def _ranges(max_id: int, keyed_rows: list[tuple[int, tuple[int, ...]]]) -> tuple[tuple[int, int], ...]:
    ranges: list[tuple[int, int]] = [(0, 0)] * (max_id + 1)
    idx = 0
    for entity_id in range(max_id + 1):
        start = idx
        while idx < len(keyed_rows) and keyed_rows[idx][0] == entity_id:
            idx += 1
        ranges[entity_id] = (start, idx)
    return tuple(ranges)


def _format_module(**items: Any) -> str:
    lines = ["# Generated by roco.compiler.artifact. Do not edit by hand.", ""]
    for name, value in items.items():
        rendered = pprint.pformat(value, width=100, sort_dicts=True)
        lines.append(f"{name} = {rendered}")
    lines.append("")
    return "\n".join(lines)


def compile_artifacts(
    db_path: Path | None = None,
    *,
    hot_path: Path = HOT_PATH,
    debug_path: Path = DEBUG_PATH,
) -> tuple[Path, Path]:
    conn = _connect(db_path)
    try:
        source_hash = content_hash(_source_payload(conn))
        elements = tuple(row["name"] for row in _rows(conn, "SELECT id, name FROM elements ORDER BY id"))
        max_pet_id = conn.execute("SELECT COALESCE(MAX(id), 0) FROM pets").fetchone()[0]
        max_skill_id = conn.execute("SELECT COALESCE(MAX(id), 0) FROM skills").fetchone()[0]
        max_ability_id = conn.execute("SELECT COALESCE(MAX(id), 0) FROM abilities").fetchone()[0]

        pets: list[tuple[int, int, int, int, int, int, int, int, int, int]] = [(0, 0, 0, 0, 0, 0, 0, 0, 0, 0)] * (max_pet_id + 1)
        pet_names: list[str] = [""] * (max_pet_id + 1)
        for row in _rows(conn, "SELECT id, name, hp, atk_phys, atk_mag, def_phys, def_mag, speed, element_primary_id, element_secondary_id, ability_id FROM pets ORDER BY id"):
            pets[row["id"]] = (
                row["id"],
                row["hp"],
                row["atk_phys"],
                row["atk_mag"],
                row["def_phys"],
                row["def_mag"],
                row["speed"],
                row["element_primary_id"],
                row["element_secondary_id"] if row["element_secondary_id"] is not None else -1,
                row["ability_id"] or 0,
            )
            pet_names[row["id"]] = row["name"]

        skills: list[tuple[int, int, int, int, int, int, int]] = [(0, 0, 0, 0, 0, 0, 1)] * (max_skill_id + 1)
        skill_names: list[str] = [""] * (max_skill_id + 1)
        skill_ids_by_name: dict[str, int] = {}
        for row in _rows(conn, "SELECT id, name, element_id, category_code, energy, power, flags FROM skills ORDER BY id"):
            skills[row["id"]] = (
                row["id"],
                row["element_id"],
                row["category_code"],
                row["energy"],
                row["power"],
                row["flags"],
                1,
            )
            skill_names[row["id"]] = row["name"]
            skill_ids_by_name[row["name"]] = row["id"]

        pet_skills: list[tuple[int, int, int, int]] = [(0, 0, 0, 0)] * (max_pet_id + 1)
        skill_accum: list[list[int]] = [[] for _ in range(max_pet_id + 1)]
        for row in _rows(conn, "SELECT pet_id, skill_id FROM pet_skills WHERE skill_id IS NOT NULL ORDER BY pet_id, sort_order, id"):
            if len(skill_accum[row["pet_id"]]) < 4:
                skill_accum[row["pet_id"]].append(row["skill_id"])
        for pet_id, ids in enumerate(skill_accum):
            pet_skills[pet_id] = tuple((ids + [0, 0, 0, 0])[:4])  # type: ignore[assignment]

        leader_form_by_pet = [0] * (max_pet_id + 1)
        for row in _rows(conn, "SELECT source_pet_id, leader_pet_id FROM pet_transforms ORDER BY source_pet_id"):
            if 0 <= row["source_pet_id"] <= max_pet_id:
                leader_form_by_pet[row["source_pet_id"]] = row["leader_pet_id"]

        pet_ids_by_name = {name: idx for idx, name in enumerate(pet_names) if name}
        form_transform_by_pet = [0] * (max_pet_id + 1)
        for name, pet_id in pet_ids_by_name.items():
            if "棋骑士" not in name:
                continue
            target = name.replace("棋骑士", "棋绮后")
            form_transform_by_pet[pet_id] = pet_ids_by_name.get(target, 0)

        skipped: dict[int, int] = {}
        skill_effect_keyed: list[tuple[int, tuple[int, ...]]] = []
        for row in _rows(conn, "SELECT skill_id, timing_code, tag_code, flags, params_json, condition, sort_order FROM skill_effects ORDER BY skill_id, sort_order, id"):
            effect = _effect_row(row, skill_ids_by_name)
            if effect[4] < 0 or effect[0] not in KERNEL_SUPPORTED_TAG_SET:
                skipped[effect[0]] = skipped.get(effect[0], 0) + 1
            else:
                skill_effect_keyed.append((row["skill_id"], effect))
        skill_effect_rows = tuple(item[1] for item in skill_effect_keyed)

        ability_effect_keyed: list[tuple[int, tuple[int, ...]]] = []
        ability_flags = [0] * (max_ability_id + 1)
        for row in _rows(conn, "SELECT ability_id, timing_code, tag_code, flags, params_json, condition, sort_order FROM ability_effects ORDER BY ability_id, sort_order, id"):
            effect = _effect_row(row, skill_ids_by_name)
            flag = ABILITY_FLAG_TAGS.get(effect[0])
            if flag is not None:
                ability_flags[row["ability_id"]] |= int(flag)
                continue
            if effect[4] < 0 or effect[0] not in KERNEL_SUPPORTED_TAG_SET:
                skipped[effect[0]] = skipped.get(effect[0], 0) + 1
            else:
                ability_effect_keyed.append((row["ability_id"], effect))
        ability_effect_rows = tuple(item[1] for item in ability_effect_keyed)
        skipped_effect_stats = tuple(sorted(skipped.items()))

        hot = _format_module(
            CATALOG_VERSION=CATALOG_VERSION,
            SCHEMA_VERSION=SCHEMA_VERSION,
            SOURCE_HASH=source_hash,
            ELEMENT_COUNT=len(elements),
            PETS=tuple(pets),
            SKILLS=tuple(skills),
            PET_SKILLS=tuple(pet_skills),
            LEADER_FORM_BY_PET=tuple(leader_form_by_pet),
            FORM_TRANSFORM_BY_PET=tuple(form_transform_by_pet),
            TYPE_CHART_BPS=_type_chart_bps(elements),
            SKILL_EFFECT_ROWS=skill_effect_rows,
            SKILL_EFFECT_RANGES=_ranges(max_skill_id, skill_effect_keyed),
            ABILITY_EFFECT_ROWS=ability_effect_rows,
            ABILITY_EFFECT_RANGES=_ranges(max_ability_id, ability_effect_keyed),
            ABILITY_FLAGS=tuple(ability_flags),
            SKIPPED_EFFECT_STATS=skipped_effect_stats,
        )
        debug = _format_module(
            CATALOG_VERSION=CATALOG_VERSION,
            SCHEMA_VERSION=SCHEMA_VERSION,
            SOURCE_HASH=source_hash,
            ELEMENT_NAMES=elements,
            PET_NAMES=tuple(pet_names),
            SKILL_NAMES=tuple(skill_names),
            PET_IDS_BY_NAME={name: idx for idx, name in enumerate(pet_names) if name},
            SKILL_IDS_BY_NAME={name: idx for idx, name in enumerate(skill_names) if name},
            LEADER_FORM_BY_PET=tuple(leader_form_by_pet),
            FORM_TRANSFORM_BY_PET=tuple(form_transform_by_pet),
            BLOODLINE_IDS_BY_NAME={row["name"]: row["id"] for row in _rows(conn, "SELECT id, name FROM bloodlines ORDER BY id")},
            BLOODLINE_MAGIC_IDS_BY_NAME={row["name"]: row["id"] for row in _rows(conn, "SELECT id, name FROM bloodline_magics ORDER BY id")},
            SKIPPED_EFFECT_STATS=tuple(
                (PakOp(tag).name if tag in PakOp._value2member_map_ else str(tag), count)
                for tag, count in skipped_effect_stats
            ),
        )
        hot_path.parent.mkdir(parents=True, exist_ok=True)
        debug_path.parent.mkdir(parents=True, exist_ok=True)
        hot_path.write_text(hot, encoding="utf-8")
        debug_path.write_text(debug, encoding="utf-8")
        return hot_path, debug_path
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=None)
    args = parser.parse_args()
    hot_path, debug_path = compile_artifacts(args.db)
    print(f"Compiled kernel catalog -> {hot_path}")
    print(f"Compiled debug catalog -> {debug_path}")


if __name__ == "__main__":
    main()
