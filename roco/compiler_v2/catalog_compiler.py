"""Compile SQLite catalog rows into hot/debug Python catalogs for the fixed kernel."""

from __future__ import annotations

import argparse
import json
import pprint
import sqlite3
from pathlib import Path
from typing import Any

from roco.data.utils import DB_DIR, ROOT, content_hash
from roco.compiler_v2 import ability_flags as ability_flag_artifact
from roco.generated.type_chart import TYPE_CHART_BPS as _PAK_TYPE_CHART_BPS

CATALOG_VERSION = 1
SCHEMA_VERSION = "kernel-v2"
HOT_PATH = ROOT / "roco" / "generated" / "catalog_hot.py"
DEBUG_PATH = ROOT / "roco" / "generated" / "catalog_debug.py"

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
        "skills": [
            tuple(row)
            for row in _rows(
                conn,
                "SELECT id, name, element_id, category_code, skill_dam_type, "
                "energy, power, flags, effect_text, flavor_text "
                "FROM skills ORDER BY id",
            )
        ],
        "abilities": [
            tuple(row)
            for row in _rows(
                conn,
                "SELECT id, name, description, flags, source_version FROM abilities ORDER BY id",
            )
        ],
        "pet_skills": [tuple(row) for row in _rows(conn, "SELECT pet_id, skill_id, sort_order FROM pet_skills WHERE skill_id IS NOT NULL ORDER BY pet_id, sort_order, id")],
        "skill_effects": [tuple(row) for row in _rows(conn, "SELECT skill_id, timing_code, tag_code, flags, params_json, condition, sort_order FROM skill_effects ORDER BY skill_id, sort_order, id")],
        "ability_effects": [tuple(row) for row in _rows(conn, "SELECT ability_id, timing_code, tag_code, flags, params_json, condition, sort_order FROM ability_effects ORDER BY ability_id, sort_order, id")],
        # Pak effect-id provenance for ability flag artifact generation.
        # Inputs to ABILITY_FLAGS — must be in the hash so that adding a
        # rule row, renaming an effect, or shifting the canonical sort
        # order invalidates SOURCE_HASH alongside the catalog rebuild.
        "ability_effect_ids": [tuple(row) for row in _rows(conn, "SELECT ability_id, source_ability_id, effect_id, timing_code, target_type, success_rate, sort_order FROM ability_effect_ids ORDER BY ability_id, sort_order")],
        "ability_flags_from_effects_rules": list(ability_flag_artifact.normalized_payload()),
        "bloodlines": [tuple(row) for row in _rows(conn, "SELECT id, code, name, kind, element_id FROM bloodlines ORDER BY id")],
        "bloodline_magics": [tuple(row) for row in _rows(conn, "SELECT id, code, name, uses_per_battle FROM bloodline_magics ORDER BY id")],
    }


def _type_chart_bps(element_names: tuple[str, ...]) -> tuple[tuple[int, ...], ...]:
    """Type effectiveness BPS table consumed by the kernel hot catalog.

    Pak ``TYPE_DICTIONARY.json`` is the single source of truth here —
    ``gen_prefix_map`` reads it once and emits the compiled table to
    :mod:`roco.generated.type_chart`.  We pass it through unchanged so
    ``catalog_hot.TYPE_CHART_BPS`` is the same data the codegen wrote;
    the retired hand-curated type-chart module
    is retained only for the display/test layer.

    The ``element_names`` argument is used only to assert the generated
    type chart still matches the pak-derived element table, so drift fails
    loudly rather than silently truncating rows.
    """
    if len(element_names) != len(_PAK_TYPE_CHART_BPS):
        raise RuntimeError(
            f"elements table has {len(element_names)} rows but pak type chart "
            f"has {len(_PAK_TYPE_CHART_BPS)} — regenerate via gen_prefix_map"
        )
    return _PAK_TYPE_CHART_BPS


def _effect_row(row: sqlite3.Row) -> tuple[int, ...]:
    """Pass through DB values directly — codegen already assigned handler indices and params."""
    params = json.loads(row["params_json"] or "{}")
    return (
        int(row["tag_code"]),       # handler_idx (from codegen)
        int(row["timing_code"]),    # timing (pak cast_moment)
        int(params.get("target", 0)),
        0,                           # flags
        0,                           # cond
        int(params.get("p0", 0)),
        int(params.get("p1", 0)),
        int(params.get("p2", 0)),
        int(params.get("p3", 0)),
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
    lines = ["# Generated by roco.compiler_v2.catalog_compiler. Do not edit by hand.", ""]
    for name, value in items.items():
        rendered = pprint.pformat(value, width=100, sort_dicts=True)
        lines.append(f"{name} = {rendered}")
    lines.append("")
    return "\n".join(lines)


def compile_catalogs(
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

        skills: list[tuple[int, int, int, int, int, int, int, int]] = [(0, 0, 0, 0, 0, 0, 1, 0)] * (max_skill_id + 1)
        skill_names: list[str] = [""] * (max_skill_id + 1)
        skill_effect_texts: list[str] = [""] * (max_skill_id + 1)
        skill_flavor_texts: list[str] = [""] * (max_skill_id + 1)
        skill_ids_by_name: dict[str, int] = {}
        skill_ids_by_text: dict[str, int] = {}
        for row in _rows(conn, "SELECT id, name, element_id, category_code, skill_dam_type, energy, power, flags, effect_text, flavor_text FROM skills ORDER BY id"):
            skills[row["id"]] = (
                row["id"],
                row["element_id"],
                row["category_code"],
                row["energy"],
                row["power"],
                row["flags"],
                1,
                row["skill_dam_type"],
            )
            skill_names[row["id"]] = row["name"]
            effect_text = row["effect_text"] or ""
            flavor_text = row["flavor_text"] or ""
            skill_effect_texts[row["id"]] = effect_text
            skill_flavor_texts[row["id"]] = flavor_text
            skill_ids_by_name[row["name"]] = row["id"]
            for text_key in (row["effect_text"] or "", row["flavor_text"] or ""):
                if text_key and text_key not in skill_ids_by_text:
                    skill_ids_by_text[text_key] = row["id"]

        ability_names: list[str] = [""] * (max_ability_id + 1)
        ability_descriptions: list[str] = [""] * (max_ability_id + 1)
        for row in _rows(conn, "SELECT id, name, description FROM abilities ORDER BY id"):
            ability_names[row["id"]] = row["name"]
            ability_descriptions[row["id"]] = row["description"] or ""

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

        skill_effect_keyed: list[tuple[int, tuple[int, ...]]] = []
        for row in _rows(conn, "SELECT skill_id, timing_code, tag_code, flags, params_json, condition, sort_order FROM skill_effects ORDER BY skill_id, sort_order, id"):
            effect = _effect_row(row)
            skill_effect_keyed.append((row["skill_id"], effect))
        skill_effect_rows = tuple(item[1] for item in skill_effect_keyed)

        ability_effect_keyed: list[tuple[int, tuple[int, ...]]] = []
        ability_flags = [0] * (max_ability_id + 1)
        for row in _rows(conn, "SELECT ability_id, timing_code, tag_code, flags, params_json, condition, sort_order FROM ability_effects ORDER BY ability_id, sort_order, id"):
            effect = _effect_row(row)
            ability_effect_keyed.append((row["ability_id"], effect))
        ability_effect_rows = tuple(item[1] for item in ability_effect_keyed)
        # Populate ABILITY_FLAGS from ability flag semantics
        # joined against the ability_effect_ids provenance table.  This is
        # the "fourth outcome" path — runtime row codegen above stays
        # untouched; passive bits are layered on after.
        ability_flag_artifact.populate(
            conn,
            effect_to_flag=ability_flag_artifact.load_effect_flag_table(),
            ability_flags=ability_flags,
        )
        skipped_effect_stats: tuple[tuple[int, int], ...] = ()

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
            SKILL_DESCRIPTIONS=tuple(skill_effect_texts),
            SKILL_EFFECT_TEXTS=tuple(skill_effect_texts),
            SKILL_FLAVOR_TEXTS=tuple(skill_flavor_texts),
            ABILITY_NAMES=tuple(ability_names),
            ABILITY_DESCRIPTIONS=tuple(ability_descriptions),
            PET_IDS_BY_NAME={name: idx for idx, name in enumerate(pet_names) if name},
            SKILL_IDS_BY_NAME={name: idx for idx, name in enumerate(skill_names) if name},
            SKILL_IDS_BY_TEXT=skill_ids_by_text,
            LEADER_FORM_BY_PET=tuple(leader_form_by_pet),
            FORM_TRANSFORM_BY_PET=tuple(form_transform_by_pet),
            BLOODLINE_IDS_BY_NAME={row["name"]: row["id"] for row in _rows(conn, "SELECT id, name FROM bloodlines ORDER BY id")},
            BLOODLINE_MAGIC_IDS_BY_NAME={row["name"]: row["id"] for row in _rows(conn, "SELECT id, name FROM bloodline_magics ORDER BY id")},
            SKIPPED_EFFECT_STATS=skipped_effect_stats,
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
    hot_path, debug_path = compile_catalogs(args.db)
    print(f"Compiled kernel catalog -> {hot_path}")
    print(f"Compiled debug catalog -> {debug_path}")


if __name__ == "__main__":
    main()
