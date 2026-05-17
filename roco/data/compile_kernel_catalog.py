"""Compile SQLite catalog rows into hot/debug Python artifacts for the fixed kernel."""

from __future__ import annotations

import argparse
import json
import pprint
import sqlite3
from pathlib import Path
from typing import Any

from roco.data.utils import DB_DIR, ROOT, content_hash
from roco.engine.effect_model import EffectTag
from roco.engine.enums import AbilityFlag, WeatherType
from roco.engine.kernel_effects import KERNEL_SUPPORTED_TAGS
from roco.engine.type_chart import effectiveness_v2

CATALOG_VERSION = 1
SCHEMA_VERSION = "kernel-v1"
HOT_PATH = ROOT / "roco" / "engine" / "catalog_hot.py"
DEBUG_PATH = ROOT / "roco" / "engine" / "catalog_debug.py"

TARGET_CODES = {
    "": 0,
    "self": 1,
    "enemy": 2,
    "ally": 3,
    "team": 4,
    "enemy_team": 5,
}
COND_CODES = {"": 0}
KERNEL_SUPPORTED_TAG_SET = frozenset(KERNEL_SUPPORTED_TAGS)
WEATHER_CODES = {
    "rain": WeatherType.RAIN.value,
    "sandstorm": WeatherType.SANDSTORM.value,
    "snow": WeatherType.SNOW.value,
    "hail": WeatherType.SNOW.value,
}
ABILITY_FLAG_TAGS = {
    EffectTag.BARREL_STATE.value: AbilityFlag.BARREL_ACTIVE,
    EffectTag.FAINT_NO_MP_LOSS.value: AbilityFlag.FAKE_DEATH,
    EffectTag.BURN_NO_DECAY.value: AbilityFlag.BURN_NO_DECAY,
    EffectTag.EXTRA_POISON_TICK.value: AbilityFlag.EXTRA_POISON_TICK,
}


def _connect(path: Path | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path or DB_DIR / "data.db"))
    conn.row_factory = sqlite3.Row
    return conn


def _rows(conn: sqlite3.Connection, sql: str) -> list[sqlite3.Row]:
    return list(conn.execute(sql))


def _source_payload(conn: sqlite3.Connection) -> dict[str, Any]:
    return {
        "elements": [tuple(row) for row in _rows(conn, "SELECT id, code, name FROM elements ORDER BY id")],
        "pets": [tuple(row) for row in _rows(conn, "SELECT id, name, element_primary_id, element_secondary_id, ability_id, hp, atk_phys, atk_mag, def_phys, def_mag, speed FROM pets ORDER BY id")],
        "skills": [tuple(row) for row in _rows(conn, "SELECT id, name, element_id, category_code, energy, power, flags FROM skills ORDER BY id")],
        "pet_skills": [tuple(row) for row in _rows(conn, "SELECT pet_id, skill_id, sort_order FROM pet_skills WHERE skill_id IS NOT NULL ORDER BY pet_id, sort_order, id")],
        "skill_effects": [tuple(row) for row in _rows(conn, "SELECT skill_id, timing_code, tag_code, flags, params_json, condition, sort_order FROM skill_effects ORDER BY skill_id, sort_order, id")],
        "ability_effects": [tuple(row) for row in _rows(conn, "SELECT ability_id, timing_code, tag_code, flags, params_json, condition, sort_order FROM ability_effects ORDER BY ability_id, sort_order, id")],
    }


def _type_chart_bps(element_names: tuple[str, ...]) -> tuple[tuple[int, ...], ...]:
    rows: list[tuple[int, ...]] = []
    for move in element_names:
        rows.append(tuple(int(effectiveness_v2(move, (defender,)) * 10000) for defender in element_names))
    return tuple(rows)


def _effect_args(tag: int, params: dict[str, Any]) -> tuple[int, int, int, int]:
    if tag == EffectTag.DAMAGE.value:
        return (int(params.get("power", 0) or 0), int(params.get("hit_count", 1) or 1), 0, 0)
    if tag in {
        EffectTag.BURN.value,
        EffectTag.POISON.value,
        EffectTag.FREEZE.value,
        EffectTag.LEECH.value,
    }:
        return (int(params.get("stacks", 0) or 0), 0, 0, 0)
    if tag == EffectTag.WEATHER.value:
        weather = WEATHER_CODES.get(str(params.get("type", "")), 0)
        turns = max(1, min(15, int(params.get("turns", 5) or 5))) if weather else 0
        return (weather, turns, 0, 0)
    pct = params.get("pct")
    if pct is not None:
        return (int(float(pct) * 10000), 0, 0, 0)
    stacks = params.get("stacks")
    if stacks is not None:
        return (int(stacks), 0, 0, 0)
    amount = params.get("amount")
    if amount is not None:
        return (int(amount), 0, 0, 0)
    return (0, 0, 0, 0)


def _effect_row(row: sqlite3.Row) -> tuple[int, int, int, int, int, int, int, int, int]:
    params = json.loads(row["params_json"] or "{}")
    target = TARGET_CODES.get(str(params.get("target", "")), 0)
    condition = str(row["condition"] or params.get("condition", ""))
    cond_code = COND_CODES.get(condition, -1)
    arg0, arg1, arg2, arg3 = _effect_args(int(row["tag_code"]), params)
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
    lines = ["# Generated by roco.data.compile_kernel_catalog. Do not edit by hand.", ""]
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

        pet_skills: list[tuple[int, int, int, int]] = [(0, 0, 0, 0)] * (max_pet_id + 1)
        skill_accum: list[list[int]] = [[] for _ in range(max_pet_id + 1)]
        for row in _rows(conn, "SELECT pet_id, skill_id FROM pet_skills WHERE skill_id IS NOT NULL ORDER BY pet_id, sort_order, id"):
            if len(skill_accum[row["pet_id"]]) < 4:
                skill_accum[row["pet_id"]].append(row["skill_id"])
        for pet_id, ids in enumerate(skill_accum):
            pet_skills[pet_id] = tuple((ids + [0, 0, 0, 0])[:4])  # type: ignore[assignment]

        skipped: dict[int, int] = {}
        skill_effect_keyed: list[tuple[int, tuple[int, ...]]] = []
        for row in _rows(conn, "SELECT skill_id, timing_code, tag_code, flags, params_json, condition, sort_order FROM skill_effects ORDER BY skill_id, sort_order, id"):
            effect = _effect_row(row)
            if effect[4] < 0 or effect[0] not in KERNEL_SUPPORTED_TAG_SET:
                skipped[effect[0]] = skipped.get(effect[0], 0) + 1
            else:
                skill_effect_keyed.append((row["skill_id"], effect))
        skill_effect_rows = tuple(item[1] for item in skill_effect_keyed)

        ability_effect_keyed: list[tuple[int, tuple[int, ...]]] = []
        ability_flags = [0] * (max_ability_id + 1)
        for row in _rows(conn, "SELECT ability_id, timing_code, tag_code, flags, params_json, condition, sort_order FROM ability_effects ORDER BY ability_id, sort_order, id"):
            effect = _effect_row(row)
            flag = ABILITY_FLAG_TAGS.get(effect[0])
            if flag is not None:
                ability_flags[row["ability_id"]] |= int(flag)
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
            SKIPPED_EFFECT_STATS=tuple(
                (EffectTag(tag).name if tag in EffectTag._value2member_map_ else str(tag), count)
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
