"""Compile pak-derived primitive records into engine hot/debug catalogs."""

from __future__ import annotations

import argparse
import json
import pprint
from collections import Counter
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from roco.common.enums import ELEMENT_NAMES, SkillCategory, normalize_element_name
from roco.data import ability_flags as ability_flag_artifact
from roco.compiler_v2.build import build_static_bundle
from roco.compiler_v2.static_artifacts.bloodline_magic import build_bloodline_magic_tables
from roco.compiler_v2.static_artifacts.core import build_type_chart_bps
from roco.data.action_table import (
    ACTION_CONDITIONAL,
    ACTION_EXTRA_SKILL,
    ACTION_NONE,
    ACTION_OP_LIST,
    ACTION_RANDOM,
    ACTION_TRIGGER_REGISTER,
    ActionInterner,
)
from roco.data.canonical import load_canonical_records
from roco.data.parse_pak import DEFAULT_PAK_DATA_DIR
from roco.data.utils import ROOT, RULES_DIR, content_hash, iter_jsonl
from roco.engine.artifacts.linked_op import LinkGapError, LinkInertError, LinkedAction, LinkedOp
from roco.engine.artifacts.pak_ref_after_skill import build_after_skill_trigger_rows
from roco.engine.artifacts.pak_ref_linker import _link_ref_id
from roco.engine.artifacts.primitive_linker import link_primitive_rows
from roco.generated.runtime.handler_order import op_index

CATALOG_VERSION = 1
SCHEMA_VERSION = "kernel-v2"
CATALOG_GEN_DIR = ROOT / "roco" / "generated" / "catalog"
HOT_PATH = CATALOG_GEN_DIR / "hot.py"
DEBUG_PATH = CATALOG_GEN_DIR / "debug.py"
ACTION_PATH = CATALOG_GEN_DIR / "actions.py"
ENGINE_LINK_GAPS_PATH = ROOT / "roco" / "generated" / "audit" / "engine_link_gaps.jsonl"
ENGINE_LINK_INERT_PATH = ROOT / "roco" / "generated" / "audit" / "engine_link_inert.jsonl"

Record = Mapping[str, Any]
AbilityEffectIdRow = tuple[int, int, int, int, int, int, int]

_CATEGORY_MAP = {
    "物攻": SkillCategory.PHYSICAL,
    "魔攻": SkillCategory.MAGICAL,
    "防御": SkillCategory.DEFENSE,
    "状态": SkillCategory.STATUS,
}


def _safe_int(value: object) -> int | None:
    try:
        if value in (None, ""):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _required_int(value: object, default: int = 0) -> int:
    parsed = _safe_int(value)
    return default if parsed is None else parsed


def _records(records: Iterable[Record], kind: str) -> list[Record]:
    rows = list(records)
    bad = [str(row.get("name", row.get("id", ""))) for row in rows if row.get("kind") != kind]
    if bad:
        raise ValueError(f"expected canonical kind={kind!r}, got mismatches: {', '.join(bad[:5])}")
    return rows


def _element_id(raw: object) -> int:
    name = normalize_element_name(str(raw or "普通"))
    return ELEMENT_NAMES.index(name)


def _maybe_element_id(raw: object) -> int | None:
    if not raw:
        return None
    return _element_id(raw)


def _category_code(raw: object) -> int:
    if isinstance(raw, SkillCategory):
        return int(raw.value)
    cat = _CATEGORY_MAP.get(str(raw or "").strip())
    if cat is None:
        raise ValueError(f"unknown skill category: {raw!r}")
    return int(cat.value)


def _type_chart_bps(element_names: tuple[str, ...]) -> tuple[tuple[int, ...], ...]:
    """Return the pak-derived type-effectiveness table used by the kernel."""

    chart = build_type_chart_bps(build_static_bundle())
    if len(element_names) != len(chart):
        raise RuntimeError(
            f"elements table has {len(element_names)} rows but pak type chart "
            f"has {len(chart)}; regenerate via gen_prefix_map"
        )
    return chart


def _effect_rows(
    row_tuple: Iterable[object],
    *,
    source_name: str,
    actions: ActionInterner,
    link_gaps: list[dict[str, Any]],
    link_inert: list[dict[str, Any]],
) -> tuple[tuple[int, ...], ...]:
    rows: list[tuple[int, ...]] = []
    try:
        linked_rows = link_primitive_rows(row_tuple, source_name=source_name)
    except LinkGapError as exc:
        link_gaps.append(exc.gap.as_record())
        return ()
    except LinkInertError as exc:
        link_inert.append(exc.inert.as_record())
        return ()
    for linked in linked_rows:
        if isinstance(linked, LinkedOp):
            p0, p1, p2, p3 = linked.runtime_args()
            rows.append((
                op_index(linked.op_name),
                linked.timing,
                linked.target,
                0,
                0,
                p0,
                p1,
                p2,
                p3,
            ))
            continue
        if isinstance(linked, LinkedAction):
            rows.append((
                op_index("op_queue_action"),
                linked.timing,
                linked.target,
                0,
                0,
                actions.intern(linked),
                0,
                0,
                0,
            ))
            continue
        raise RuntimeError(f"{source_name!r} linked unsupported row object {linked!r}")
    return tuple(rows)


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
    lines = ["# Generated by roco.data.catalog_compiler. Do not edit by hand.", ""]
    for name, value in items.items():
        rendered = pprint.pformat(value, width=100, sort_dicts=True)
        lines.append(f"{name} = {rendered}")
    lines.append("")
    return "\n".join(lines)


def _leader_transform_manual() -> dict[str, str]:
    path = RULES_DIR / "leader_transforms_manual.jsonl"
    if not path.exists():
        return {}
    rules: dict[str, str] = {}
    for record in iter_jsonl(path):
        source = str(record.get("source", "") or record.get("name", "")).strip()
        target = str(record.get("target", "") or record.get("leader", "")).strip()
        if source and target:
            rules[source] = target
    return rules


def _leader_transform_rows(
    pet_records: Iterable[Record],
    pet_ids_by_name: Mapping[str, int],
) -> list[tuple[int, int, str]]:
    pet_rows = [
        {
            "id": pet_ids_by_name[str(row["name"])],
            "name": str(row["name"]),
            "lineage_key": str(row.get("lineage_key") or row["name"]),
            "form_type": str(row.get("form_type") or ""),
        }
        for row in pet_records
    ]
    pets_by_name = {row["name"]: row for row in pet_rows}
    rows_by_lineage: dict[str, list[dict[str, object]]] = {}
    for row in pet_rows:
        rows_by_lineage.setdefault(str(row["lineage_key"] or row["name"]), []).append(row)

    result: dict[int, tuple[int, int, str]] = {}
    for source_name, leader_name in _leader_transform_manual().items():
        source = pets_by_name.get(source_name)
        leader = pets_by_name.get(leader_name)
        if source is None or leader is None:
            continue
        result[int(source["id"])] = (int(source["id"]), int(leader["id"]), "manual")

    for lineage_rows in rows_by_lineage.values():
        leaders = [row for row in lineage_rows if row["form_type"] == "首领形态"]
        if len(leaders) != 1:
            preferred = [
                row for row in leaders
                if "#" not in str(row["name"]) and not str(row["name"]).startswith("首领-")
            ]
            if len(preferred) == 1:
                leaders = preferred
            else:
                continue
        if len(leaders) != 1:
            continue
        leader_id = int(leaders[0]["id"])
        for row in lineage_rows:
            source_id = int(row["id"])
            result.setdefault(source_id, (source_id, leader_id, "auto_lineage"))
    return [result[key] for key in sorted(result)]


def _ability_effect_id_rows(
    ability_records: Iterable[Record],
    ability_ids_by_name: Mapping[str, int],
) -> list[AbilityEffectIdRow]:
    rows: list[AbilityEffectIdRow] = []
    for record in ability_records:
        name = str(record.get("name", "")).strip()
        if not name:
            continue
        ability_id = ability_ids_by_name[name]
        source_fields = record.get("source_fields") or {}
        source_ability_id = int(record.get("source_id") or source_fields.get("id") or 0)
        entries: list[Mapping[str, Any]] = []
        for key in ("skill_result", "effect_list"):
            raw_entries = source_fields.get(key) if isinstance(source_fields, Mapping) else None
            if isinstance(raw_entries, list):
                entries.extend(item for item in raw_entries if isinstance(item, Mapping))
        for sort_order, entry in enumerate(entries):
            effect_id = int(entry.get("effect_id", 0) or 0)
            if effect_id <= 0:
                continue
            rows.append((
                ability_id,
                source_ability_id,
                effect_id,
                int(entry.get("cast_moment", 0) or 0),
                int(entry.get("result_target_type", 0) or 0),
                int(entry.get("success_rate", 0) or 0),
                sort_order,
            ))
    return rows


def compile_catalogs(
    pak_dir: Path | None = None,
    *,
    hot_path: Path = HOT_PATH,
    debug_path: Path = DEBUG_PATH,
    action_path: Path = ACTION_PATH,
    engine_link_gaps_path: Path = ENGINE_LINK_GAPS_PATH,
    engine_link_inert_path: Path | None = None,
) -> tuple[Path, Path]:
    if engine_link_inert_path is None:
        engine_link_inert_path = engine_link_gaps_path.with_name("engine_link_inert.jsonl")
    if action_path == ACTION_PATH and hot_path != HOT_PATH:
        action_path = hot_path.with_name("actions.py")
    canonical = load_canonical_records(pak_dir or DEFAULT_PAK_DATA_DIR)
    skill_records = _records(canonical["skills"], "skill")
    ability_records = _records(canonical["abilities"], "ability")
    pet_records = _records(canonical["pets"], "pet")

    elements = tuple(ELEMENT_NAMES)
    skill_ids_by_name = {str(row["name"]): idx for idx, row in enumerate(skill_records, start=1)}
    skill_ids_by_source = {
        int(row["source_id"]): idx
        for idx, row in enumerate(skill_records, start=1)
        if _safe_int(row.get("source_id")) is not None
    }
    ability_ids_by_name = {str(row["name"]): idx for idx, row in enumerate(ability_records, start=1)}
    pet_ids_by_name = {str(row["name"]): idx for idx, row in enumerate(pet_records, start=1)}

    max_pet_id = len(pet_records)
    max_skill_id = len(skill_records)
    max_ability_id = len(ability_records)

    pets: list[tuple[int, int, int, int, int, int, int, int, int, int]] = [
        (0, 0, 0, 0, 0, 0, 0, 0, 0, 0)
    ] * (max_pet_id + 1)
    pet_names: list[str] = [""] * (max_pet_id + 1)
    pet_source_rows: list[tuple[Any, ...]] = []
    for pet_id, row in enumerate(pet_records, start=1):
        name = str(row["name"])
        elements_raw = tuple(row.get("elements", ())) + ("", "")
        stats = row.get("stats") or {}
        ability_name = str(row.get("ability", "")).strip()
        ability_id = ability_ids_by_name.get(ability_name, 0)
        if ability_name and not str(row.get("ability_description", "")).strip():
            raise ValueError(f"pet {name} has ability {ability_name!r} but empty ability_description")
        primary = _element_id(elements_raw[0] or "普通")
        secondary = _maybe_element_id(elements_raw[1] or "")
        pet_tuple = (
            pet_id,
            _required_int(stats.get("hp"), 1),
            _required_int(stats.get("atk_phys"), 0),
            _required_int(stats.get("atk_mag"), 0),
            _required_int(stats.get("def_phys"), 0),
            _required_int(stats.get("def_mag"), 0),
            _required_int(stats.get("speed"), 0),
            primary,
            secondary if secondary is not None else -1,
            ability_id,
        )
        pets[pet_id] = pet_tuple
        pet_names[pet_id] = name
        pet_source_rows.append((
            pet_id,
            name,
            str(row.get("lineage_key", "")),
            str(row.get("form_type", "")),
            primary,
            secondary,
            ability_id,
            *pet_tuple[1:7],
        ))

    skills: list[tuple[int, int, int, int, int, int, int, int]] = [
        (0, 0, 0, 0, 0, 0, 1, 0)
    ] * (max_skill_id + 1)
    skill_names: list[str] = [""] * (max_skill_id + 1)
    skill_effect_texts: list[str] = [""] * (max_skill_id + 1)
    skill_flavor_texts: list[str] = [""] * (max_skill_id + 1)
    skill_ids_by_text: dict[str, int] = {}
    skill_source_rows: list[tuple[Any, ...]] = []
    skill_effect_keyed: list[tuple[int, tuple[int, ...]]] = []
    skill_effect_source_rows: list[tuple[Any, ...]] = []
    engine_link_gaps: list[dict[str, Any]] = []
    engine_link_inert: list[dict[str, Any]] = []
    action_interner = ActionInterner()
    for skill_id, row in enumerate(skill_records, start=1):
        name = str(row["name"])
        element_id = _element_id(row.get("element", "普通"))
        category_code = _category_code(row.get("category", "物攻"))
        skill_dam_type = _required_int(row.get("skill_dam_type"), 0)
        energy = _required_int(row.get("energy"), 0)
        power = _required_int(row.get("power"), 0)
        flags = _required_int(row.get("flags"), 0)
        effect_text = str(row.get("effect_text") or "")
        flavor_text = str(row.get("flavor_text") or "")
        skills[skill_id] = (skill_id, element_id, category_code, energy, power, flags, 1, skill_dam_type)
        skill_names[skill_id] = name
        skill_effect_texts[skill_id] = effect_text
        skill_flavor_texts[skill_id] = flavor_text
        for text_key in (effect_text, flavor_text):
            if text_key and text_key not in skill_ids_by_text:
                skill_ids_by_text[text_key] = skill_id
        skill_source_rows.append((
            skill_id,
            name,
            element_id,
            category_code,
            skill_dam_type,
            energy,
            power,
            flags,
            effect_text,
            flavor_text,
        ))
        for order, raw_effect in enumerate(row.get("effect_rows", ()) or ()):
            for effect in _effect_rows(
                raw_effect,
                source_name=name,
                actions=action_interner,
                link_gaps=engine_link_gaps,
                link_inert=engine_link_inert,
            ):
                skill_effect_keyed.append((skill_id, effect))
                skill_effect_source_rows.append((skill_id, *effect, order))

    ability_names: list[str] = [""] * (max_ability_id + 1)
    ability_descriptions: list[str] = [""] * (max_ability_id + 1)
    ability_source_rows: list[tuple[Any, ...]] = []
    ability_effect_keyed: list[tuple[int, tuple[int, ...]]] = []
    ability_effect_source_rows: list[tuple[Any, ...]] = []
    for ability_id, row in enumerate(ability_records, start=1):
        name = str(row["name"])
        desc = str(row.get("description") or "")
        ability_names[ability_id] = name
        ability_descriptions[ability_id] = desc
        ability_source_rows.append((
            ability_id,
            name,
            desc,
            _required_int(row.get("flags"), 0),
            str(row.get("source_version", "")),
        ))
        for order, raw_effect in enumerate(row.get("effect_rows", ()) or ()):
            for effect in _effect_rows(
                raw_effect,
                source_name=name,
                actions=action_interner,
                link_gaps=engine_link_gaps,
                link_inert=engine_link_inert,
            ):
                ability_effect_keyed.append((ability_id, effect))
                ability_effect_source_rows.append((ability_id, *effect, order))

    pet_skills: list[tuple[int, int, int, int]] = [(0, 0, 0, 0)] * (max_pet_id + 1)
    pet_skill_source_rows: list[tuple[int, int, int]] = []
    for pet_id, row in enumerate(pet_records, start=1):
        ids: list[int] = []
        for link in row.get("skills", ()) or ():
            skill_id = skill_ids_by_name.get(str(link.get("name", "")).strip())
            if not skill_id:
                source_id = _safe_int(link.get("source_id"))
                skill_id = skill_ids_by_source.get(source_id or 0, 0)
            if not skill_id:
                continue
            pet_skill_source_rows.append((pet_id, skill_id, _required_int(link.get("sort_order"), 0)))
            if len(ids) < 4:
                ids.append(skill_id)
        pet_skills[pet_id] = tuple((ids + [0, 0, 0, 0])[:4])  # type: ignore[assignment]

    leader_transform_rows = _leader_transform_rows(pet_records, pet_ids_by_name)
    leader_form_by_pet = [0] * (max_pet_id + 1)
    for source_id, leader_id, _reason in leader_transform_rows:
        if 0 <= source_id <= max_pet_id:
            leader_form_by_pet[source_id] = leader_id

    form_transform_by_pet = [0] * (max_pet_id + 1)
    for name, pet_id in pet_ids_by_name.items():
        if "棋骑士" not in name:
            continue
        target = name.replace("棋骑士", "棋绮后")
        form_transform_by_pet[pet_id] = pet_ids_by_name.get(target, 0)

    ability_effect_id_rows = _ability_effect_id_rows(ability_records, ability_ids_by_name)
    ability_flags = [0] * (max_ability_id + 1)
    effect_to_flag = ability_flag_artifact.load_effect_flag_table()
    ability_flag_artifact.populate(
        ability_effect_id_rows,
        effect_to_flag=effect_to_flag,
        ability_flags=ability_flags,
    )
    bloodline_tables = build_bloodline_magic_tables(build_static_bundle())
    bloodline_catalog_rows = bloodline_tables["bloodline_catalog_rows"]
    bloodline_magic_catalog_rows = bloodline_tables["supported_magic_catalog_rows"]
    after_skill_triggers = build_after_skill_trigger_rows(action_interner, link_ref_id=_link_ref_id)
    action_rows = action_interner.rows()

    source_hash = content_hash({
        "elements": tuple((idx, name) for idx, name in enumerate(elements)),
        "pets": tuple(pet_source_rows),
        "pet_transforms": tuple(leader_transform_rows),
        "skills": tuple(skill_source_rows),
        "abilities": tuple(ability_source_rows),
        "pet_skills": tuple(pet_skill_source_rows),
        "skill_effects": tuple(skill_effect_source_rows),
        "ability_effects": tuple(ability_effect_source_rows),
        "ability_effect_ids": tuple(ability_effect_id_rows),
        "ability_flags_from_effects_rules": ability_flag_artifact.normalized_payload(effect_to_flag),
        "bloodlines": tuple(bloodline_catalog_rows),
        "bloodline_magics": tuple(bloodline_magic_catalog_rows),
        "after_skill_triggers": after_skill_triggers,
        "actions": action_rows,
    })
    skipped_effect_stats = tuple(sorted(Counter(str(row["reason"]) for row in engine_link_gaps).items()))

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
        SKILL_EFFECT_ROWS=tuple(item[1] for item in skill_effect_keyed),
        SKILL_EFFECT_RANGES=_ranges(max_skill_id, skill_effect_keyed),
        ABILITY_EFFECT_ROWS=tuple(item[1] for item in ability_effect_keyed),
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
        PET_IDS_BY_NAME=pet_ids_by_name,
        SKILL_IDS_BY_NAME=skill_ids_by_name,
        SKILL_IDS_BY_TEXT=skill_ids_by_text,
        LEADER_FORM_BY_PET=tuple(leader_form_by_pet),
        FORM_TRANSFORM_BY_PET=tuple(form_transform_by_pet),
        BLOODLINE_IDS_BY_NAME={row[2]: row[0] for row in bloodline_catalog_rows},
        BLOODLINE_MAGIC_IDS_BY_NAME={row[2]: row[0] for row in bloodline_magic_catalog_rows},
        SKIPPED_EFFECT_STATS=skipped_effect_stats,
    )
    hot_path.parent.mkdir(parents=True, exist_ok=True)
    debug_path.parent.mkdir(parents=True, exist_ok=True)
    action_path.parent.mkdir(parents=True, exist_ok=True)
    (action_path.parent / "__init__.py").write_text('"""Generated runtime catalogs."""\n', encoding="utf-8")
    engine_link_gaps_path.parent.mkdir(parents=True, exist_ok=True)
    engine_link_inert_path.parent.mkdir(parents=True, exist_ok=True)
    hot_path.write_text(hot, encoding="utf-8")
    debug_path.write_text(debug, encoding="utf-8")
    action_path.write_text(
        _format_module(
            ACTION_NONE=ACTION_NONE,
            ACTION_OP_LIST=ACTION_OP_LIST,
            ACTION_EXTRA_SKILL=ACTION_EXTRA_SKILL,
            ACTION_RANDOM=ACTION_RANDOM,
            ACTION_CONDITIONAL=ACTION_CONDITIONAL,
            ACTION_TRIGGER_REGISTER=ACTION_TRIGGER_REGISTER,
            AFTER_SKILL_TRIGGERS=after_skill_triggers,
            ACTIONS=action_rows,
        ),
        encoding="utf-8",
    )
    engine_link_gaps_path.write_text(
        "".join(
            json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
            for record in engine_link_gaps
        ),
        encoding="utf-8",
    )
    engine_link_inert_path.write_text(
        "".join(
            json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
            for record in engine_link_inert
        ),
        encoding="utf-8",
    )
    return hot_path, debug_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pak-dir", type=Path, default=DEFAULT_PAK_DATA_DIR)
    args = parser.parse_args()
    hot_path, debug_path = compile_catalogs(args.pak_dir)
    print(f"Compiled kernel catalog -> {hot_path}")
    print(f"Compiled debug catalog -> {debug_path}")


if __name__ == "__main__":
    main()
