"""Import canonical records into the normalized SQLite data store."""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from roco.data.canonical import load_canonical_records
from roco.data.utils import DB_DIR, RULES_DIR, content_hash, iter_jsonl
from roco.common.enums import SkillCategory, normalize_element_name


Record = Mapping[str, Any]


def _safe_int(val: object) -> int | None:
    try:
        if val is None or val == "":
            return None
        return int(val)
    except (ValueError, TypeError):
        return None


def _required_int(val: object, default: int = 0) -> int:
    parsed = _safe_int(val)
    return default if parsed is None else parsed


def _json(data: object) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def _records(records: Iterable[Record], kind: str) -> list[Record]:
    rows = list(records)
    bad = [str(row.get("name", row.get("id", ""))) for row in rows if row.get("kind") != kind]
    if bad:
        raise ValueError(f"expected canonical kind={kind!r}, got mismatches: {', '.join(bad[:5])}")
    return rows


def _element_id(conn: sqlite3.Connection, raw: str) -> int:
    name = normalize_element_name(raw)
    row = conn.execute("SELECT id FROM elements WHERE name = ?", (name,)).fetchone()
    if row is None:
        raise ValueError(f"element not seeded: {name}")
    return int(row[0])


def _maybe_element_id(conn: sqlite3.Connection, raw: str | None) -> int | None:
    if not raw:
        return None
    return _element_id(conn, raw)


def _bloodline_id(conn: sqlite3.Connection, raw: str | None) -> int | None:
    text = str(raw or "").replace("血脉", "").strip()
    if not text:
        return None
    if text == "污染":
        raise ValueError("污染血脉不能参与 PVP 队伍导入")
    if text == "首领":
        name = "首领"
    else:
        name = normalize_element_name(text)
    row = conn.execute("SELECT id FROM bloodlines WHERE name = ?", (name,)).fetchone()
    if row is None:
        raise ValueError(f"bloodline not seeded: {name}")
    return int(row[0])


def _bloodline_magic_id(conn: sqlite3.Connection, raw: str | None) -> int:
    name = str(raw or "").strip() or "愿力冲击"
    code = {
        "愿力冲击": "willpower_strike",
        "进化之力": "leader_transform",
    }.get(name, f"magic_{content_hash(name)[:12]}")
    uses = 2 if name == "愿力冲击" else 1 if name == "进化之力" else 0
    conn.execute(
        "INSERT OR IGNORE INTO bloodline_magics (code, name, uses_per_battle, description) VALUES (?, ?, ?, ?)",
        (code, name, uses, ""),
    )
    row = conn.execute("SELECT id FROM bloodline_magics WHERE name = ?", (name,)).fetchone()
    if row is None:
        raise ValueError(f"bloodline magic not inserted: {name}")
    return int(row[0])


def _category(raw: object) -> tuple[int, str]:
    if isinstance(raw, SkillCategory):
        return raw.value, _CATEGORY_NAMES[raw]
    text = str(raw or "").strip()
    cat = _CATEGORY_MAP.get(text)
    if not cat:
        raise ValueError(f"unknown skill category: {raw!r}")
    return cat.value, _CATEGORY_NAMES[cat]


_CATEGORY_MAP = {
    "物攻": SkillCategory.PHYSICAL,
    "魔攻": SkillCategory.MAGICAL,
    "防御": SkillCategory.DEFENSE,
    "状态": SkillCategory.STATUS,
}

_CATEGORY_NAMES = {
    SkillCategory.PHYSICAL: "物攻",
    SkillCategory.MAGICAL: "魔攻",
    SkillCategory.DEFENSE: "防御",
    SkillCategory.STATUS: "状态",
}

def _gap_row(
    source_type: str,
    source_name: str,
    primitive: str,
    timing_code: int | None,
    params: Mapping[str, Any] | None,
    reason: str,
) -> tuple:
    return (
        source_type,
        source_name,
        primitive,
        timing_code,
        _json(dict(params or {})),
        reason,
        0,
    )


def _insert_gaps(conn: sqlite3.Connection, rows: Iterable[tuple]) -> int:
    gap_rows = list(rows)
    if gap_rows:
        conn.executemany(
            "INSERT INTO effect_gaps (source_type, source_name, primitive, timing_code, params_json, reason, used_count) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            gap_rows,
        )
    return len(gap_rows)


def import_abilities(conn: sqlite3.Connection, abilities: Iterable[Record]) -> dict[str, int]:
    records = _records(abilities, "ability")
    rows = [
        (
            str(record["name"]),
            str(record.get("description", "")),
            _required_int(record.get("flags"), 0),
            str(record.get("source_version", "")),
        )
        for record in records
        if str(record.get("name", "")).strip()
    ]
    conn.executemany(
        "INSERT INTO abilities (name, description, flags, source_version) VALUES (?, ?, ?, ?)",
        rows,
    )
    lookup = {name: aid for aid, name in conn.execute("SELECT id, name FROM abilities")}
    effect_rows: list[tuple] = []
    gap_rows: list[tuple] = []
    ability_effect_id_rows: list[tuple] = []
    for record in records:
        name = str(record.get("name", "")).strip()
        if not name:
            continue
        owner_id = lookup[name]
        # ability_effect_ids: pak provenance of every skill_result row this
        # ability declares.  Independent of decoder outcome — even effects
        # that compile to ABILITY_FLAGS bits (AbilityFlagOutcome) are
        # recorded here so the codegen layer can join effect_id → flag
        # without re-reading canonical records.
        source_fields = record.get("source_fields") or {}
        source_ability_id = int(record.get("source_id") or source_fields.get("id") or 0)
        for sort_order, entry in enumerate(source_fields.get("skill_result") or []):
            entry_effect_id = int(entry.get("effect_id", 0) or 0)
            if entry_effect_id <= 0:
                continue
            ability_effect_id_rows.append((
                owner_id,
                source_ability_id,
                entry_effect_id,
                int(entry.get("cast_moment", 0) or 0),
                int(entry.get("result_target_type", 0) or 0),
                int(entry.get("success_rate", 0) or 0),
                sort_order,
            ))
        for order, row_tuple in enumerate(record.get("effect_rows", []) or []):
            # row_tuple = (handler_idx, timing, target, rate, p0, p1, p2, p3)
            handler_idx = row_tuple[0]
            if handler_idx <= 0:
                raise RuntimeError(
                    f"ability '{name}' produced an effect row with "
                    f"tag_code={handler_idx} — H_NOOP / 0 is forbidden at the "
                    f"compile boundary; investigate the decoder"
                )
            timing = row_tuple[1]
            target = row_tuple[2]
            rate = row_tuple[3]
            params_json = json.dumps({"target": target, "rate": rate, "p0": row_tuple[4], "p1": row_tuple[5], "p2": row_tuple[6], "p3": row_tuple[7]})
            effect_rows.append((owner_id, timing, handler_idx, 0, params_json, "", order))
        for gap in record.get("effect_gaps", []) or []:
            gap_rows.append(_gap_row(
                "ability",
                name,
                str(gap.get("primitive", "")),
                gap.get("timing_code"),
                gap.get("params") or {},
                str(gap.get("reason", "")),
            ))
    if effect_rows:
        conn.executemany(
            "INSERT INTO ability_effects (ability_id, timing_code, tag_code, flags, params_json, condition, sort_order) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            effect_rows,
        )
    if ability_effect_id_rows:
        conn.executemany(
            "INSERT INTO ability_effect_ids "
            "(ability_id, source_ability_id, effect_id, timing_code, target_type, success_rate, sort_order) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ability_effect_id_rows,
        )
    inserted_gaps = _insert_gaps(conn, gap_rows)
    print(f"  abilities: {len(lookup)} inserted")
    print(f"  ability_effects: {len(effect_rows)} inserted")
    print(f"  ability_effect_ids: {len(ability_effect_id_rows)} inserted")
    print(f"  ability effect_gaps: {inserted_gaps} inserted")
    return lookup


def import_skills(conn: sqlite3.Connection, skills: Iterable[Record]) -> dict[str, int]:
    records = _records(skills, "skill")
    rows: list[tuple] = []
    for record in records:
        category_code, category_name = _category(record.get("category", "物攻"))
        rows.append((
            str(record["name"]),
            _element_id(conn, str(record.get("element", "普通"))),
            category_code,
            category_name,
            _required_int(record.get("skill_dam_type"), 0),
            _required_int(record.get("energy"), 0),
            _required_int(record.get("power"), 0),
            str(record.get("effect_text", "")),
            str(record.get("flavor_text", "")),
            _required_int(record.get("flags"), 0),
            str(record.get("source_version", "")),
        ))
    conn.executemany(
        "INSERT INTO skills (name, element_id, category_code, category_name, skill_dam_type, energy, power, effect_text, flavor_text, flags, source_version) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    lookup = {name: sid for sid, name in conn.execute("SELECT id, name FROM skills")}
    effect_rows: list[tuple] = []
    gap_rows: list[tuple] = []
    for record in records:
        name = str(record["name"])
        owner_id = lookup[name]
        for order, row_tuple in enumerate(record.get("effect_rows", []) or []):
            # row_tuple = (handler_idx, timing, target, rate, p0, p1, p2, p3)
            handler_idx = row_tuple[0]
            if handler_idx <= 0:
                raise RuntimeError(
                    f"skill '{name}' produced an effect row with "
                    f"tag_code={handler_idx} — H_NOOP / 0 is forbidden at the "
                    f"compile boundary; investigate the decoder"
                )
            timing = row_tuple[1]
            target = row_tuple[2]
            rate = row_tuple[3]
            params_json = json.dumps({"target": target, "rate": rate, "p0": row_tuple[4], "p1": row_tuple[5], "p2": row_tuple[6], "p3": row_tuple[7]})
            effect_rows.append((owner_id, timing, handler_idx, 0, params_json, "", order))
        for gap in record.get("effect_gaps", []) or []:
            gap_rows.append(_gap_row(
                "skill",
                name,
                str(gap.get("primitive", "")),
                gap.get("timing_code"),
                gap.get("params") or {},
                str(gap.get("reason", "")),
            ))
    if effect_rows:
        conn.executemany(
            "INSERT INTO skill_effects (skill_id, timing_code, tag_code, flags, params_json, condition, sort_order) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            effect_rows,
        )
    inserted_gaps = _insert_gaps(conn, gap_rows)
    print(f"  skills: {len(lookup)} inserted")
    print(f"  skill_effects: {len(effect_rows)} inserted")
    print(f"  skill effect_gaps: {inserted_gaps} inserted")
    return lookup


def import_pets(
    conn: sqlite3.Connection,
    pets: Iterable[Record],
    skill_lookup: dict[str, int],
    ability_lookup: dict[str, int],
) -> dict[str, int]:
    records = _records(pets, "pet")
    rows: list[tuple] = []
    for record in records:
        elements = tuple(record.get("elements", ())) + ("", "")
        stats = record.get("stats", {}) or {}
        ability_name = str(record.get("ability", "")).strip()
        ability_description = str(record.get("ability_description", ""))
        if ability_name and not ability_description.strip():
            raise ValueError(f"pet {record['name']} has ability {ability_name!r} but empty ability_description")
        rows.append((
            str(record["name"]),
            str(record.get("form_name", "")),
            str(record.get("stage", "")),
            str(record.get("form_type", "")),
            str(record.get("lineage_key", "")),
            _element_id(conn, str(elements[0] or "普通")),
            _maybe_element_id(conn, str(elements[1] or "")),
            ability_lookup.get(ability_name),
            ability_description,
            _required_int(stats.get("hp"), 1),
            _required_int(stats.get("atk_phys"), 0),
            _required_int(stats.get("atk_mag"), 0),
            _required_int(stats.get("def_phys"), 0),
            _required_int(stats.get("def_mag"), 0),
            _required_int(stats.get("speed"), 0),
            str(record.get("height", "")),
            str(record.get("weight", "")),
            str(record.get("distribution", "")),
            str(record.get("description", "")),
            1 if record.get("is_shiny") else 0,
            str(record.get("evolution_cond", "")),
            str(record.get("source_version", "")),
        ))
    conn.executemany(
        "INSERT INTO pets (name, form_name, stage, form_type, lineage_key, element_primary_id, element_secondary_id, ability_id, "
        "ability_description, hp, atk_phys, atk_mag, def_phys, def_mag, speed, height, weight, distribution, description, is_shiny, evolution_cond, source_version) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    pet_lookup = {name: pid for pid, name in conn.execute("SELECT id, name FROM pets")}
    link_rows: list[tuple] = []
    for record in records:
        pet_id = pet_lookup[str(record["name"])]
        for link in record.get("skills", ()) or ():
            skill_name = str(link.get("name", "")).strip()
            if not skill_name:
                continue
            link_rows.append((
                pet_id,
                skill_lookup.get(skill_name),
                skill_name,
                str(link.get("source_type", "技能")),
                _safe_int(link.get("unlock_level")),
                _required_int(link.get("sort_order"), 0),
            ))
    conn.executemany(
        "INSERT INTO pet_skills (pet_id, skill_id, skill_name, source_type, unlock_level, sort_order) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        link_rows,
    )
    transform_rows = _leader_transform_rows(conn)
    if transform_rows:
        conn.executemany(
            "INSERT OR REPLACE INTO pet_transforms (source_pet_id, leader_pet_id, reason) VALUES (?, ?, ?)",
            transform_rows,
        )
    print(f"  pets: {len(pet_lookup)} inserted")
    print(f"  pet_skills: {len(link_rows)} links inserted")
    print(f"  pet_transforms: {len(transform_rows)} inserted")
    return pet_lookup


def _leader_transform_rows(conn: sqlite3.Connection) -> list[tuple[int, int, str]]:
    pet_rows = [
        {
            "id": int(row[0]),
            "name": str(row[1]),
            "lineage_key": str(row[2] or ""),
            "form_type": str(row[3] or ""),
        }
        for row in conn.execute("SELECT id, name, lineage_key, form_type FROM pets ORDER BY id")
    ]
    pets_by_name = {row["name"]: row for row in pet_rows}
    rows_by_lineage: dict[str, list[dict[str, object]]] = {}
    for row in pet_rows:
        key = str(row["lineage_key"] or row["name"])
        rows_by_lineage.setdefault(key, []).append(row)

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


def import_marks(conn: sqlite3.Connection, marks: Iterable[Record]) -> None:
    records = _records(marks, "mark")
    mark_rows: list[tuple] = []
    source_rows: list[tuple] = []
    for record in records:
        code = str(record.get("code", "")).strip()
        name = str(record.get("name", "")).strip()
        packed_index = _required_int(record.get("packed_index"), -1)
        polarity = str(record.get("polarity", "")).strip()
        if not code or packed_index < 0 or polarity not in {"positive", "negative"}:
            raise ValueError(f"invalid mark canonical row: {name or code}")
        mark_rows.append((
            packed_index,
            code,
            name,
            packed_index,
            polarity,
            str(record.get("stacking", "")),
            str(record.get("effect_text", "")),
            _json(record.get("mechanism", []) or []),
            _json(record.get("effects", []) or []),
        ))
    conn.executemany(
        """
        INSERT INTO marks (id, code, name, packed_index, polarity, stacking, effect_text, mechanism_json, effects_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(code) DO UPDATE SET
            name=excluded.name,
            packed_index=excluded.packed_index,
            polarity=excluded.polarity,
            stacking=excluded.stacking,
            effect_text=excluded.effect_text,
            mechanism_json=excluded.mechanism_json,
            effects_json=excluded.effects_json
        """,
        mark_rows,
    )
    mark_lookup = {code: mid for mid, code in conn.execute("SELECT id, code FROM marks")}
    for record in records:
        code = str(record.get("code", "")).strip()
        for source in record.get("source_skills", ()) or ():
            skill_name = str(source.get("skill", "")).strip()
            source_rows.append((
                mark_lookup[code],
                skill_name,
                str(source.get("description", "")),
            ))
    if source_rows:
        conn.executemany(
            "INSERT OR IGNORE INTO mark_sources (mark_id, skill_name, description) VALUES (?, ?, ?)",
            source_rows,
        )
    print(f"  marks: {len(mark_rows)} upserted")
    print(f"  mark_sources: {len(source_rows)} inserted")


def import_teams(
    conn: sqlite3.Connection,
    teams: Iterable[Record],
    pet_lookup: dict[str, int],
    skill_lookup: dict[str, int],
) -> None:
    records = _records(teams, "team")
    team_rows: list[tuple] = []
    pet_rows: list[tuple] = []
    skill_rows: list[tuple] = []

    for team in records:
        magic_name = str(team.get("bloodline_magic", "") or "愿力冲击")
        magic_id = _bloodline_magic_id(conn, magic_name)
        team_rows.append((
            str(team.get("id", "")),
            str(team.get("title", "")),
            str(team.get("author", "")),
            str(team.get("type", "")),
            magic_name,
            magic_id,
            str(team.get("description", "")),
            str(team.get("upload_date", "")),
        ))
    conn.executemany(
        "INSERT INTO teams (id, title, author, team_type, bloodline_magic, bloodline_magic_id, description, upload_date) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        team_rows,
    )

    for team in records:
        tid = str(team.get("id", ""))
        for pet in team.get("pets", []) or []:
            pet_rows.append((
                tid,
                int(pet.get("slot", 0)),
                pet_lookup.get(str(pet.get("name", ""))) or pet_lookup.get(str(pet.get("name_short", ""))),
                str(pet.get("name", "")),
                str(pet.get("name_short", "")),
                str(pet.get("bloodline", "")),
                _bloodline_id(conn, str(pet.get("bloodline", ""))),
                str(pet.get("nature", "")),
                _json(pet.get("ivs", [])),
            ))
    conn.executemany(
        "INSERT INTO team_pets (team_id, slot, pet_id, pet_name, name_short, bloodline, bloodline_id, nature, ivs_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        pet_rows,
    )

    team_pet_ids = {
        (team_id, slot): tpid
        for tpid, team_id, slot in conn.execute("SELECT id, team_id, slot FROM team_pets")
    }
    for team in records:
        tid = str(team.get("id", ""))
        for pet in team.get("pets", []) or []:
            tpid = team_pet_ids[(tid, int(pet.get("slot", 0)))]
            for i, move in enumerate(pet.get("moves", []), start=1):
                skill_rows.append((tpid, i, skill_lookup.get(move), move))
    conn.executemany(
        "INSERT INTO team_pet_skills (team_pet_id, slot, skill_id, skill_name) VALUES (?, ?, ?, ?)",
        skill_rows,
    )
    refresh_effect_gap_usage(conn)
    from roco.data.validation import assert_no_kernel_noop_rows
    assert_no_kernel_noop_rows(conn)
    from roco.data.validation import (
        assert_no_blocking_effect_gaps,
        assert_no_missing_leader_transforms,
    )
    assert_no_missing_leader_transforms(conn)
    assert_no_blocking_effect_gaps(conn)
    print(f"  teams: {len(team_rows)} inserted")
    print(f"  team_pets: {len(pet_rows)} slots inserted")
    print(f"  team_pet_skills: {len(skill_rows)} moves inserted")


def print_effect_coverage(conn: sqlite3.Connection) -> None:
    """Emit a coverage summary so silent regressions in handler mapping are visible."""
    skill_rows = conn.execute("SELECT COUNT(*) FROM skill_effects").fetchone()[0]
    skill_gaps = conn.execute(
        "SELECT COUNT(*) FROM effect_gaps WHERE source_type = 'skill'"
    ).fetchone()[0]
    skill_used_gaps = conn.execute(
        "SELECT COUNT(*) FROM effect_gaps WHERE source_type = 'skill' AND used_count > 0"
    ).fetchone()[0]
    ability_rows = conn.execute("SELECT COUNT(*) FROM ability_effects").fetchone()[0]
    ability_gaps = conn.execute(
        "SELECT COUNT(*) FROM effect_gaps WHERE source_type = 'ability'"
    ).fetchone()[0]
    ability_used_gaps = conn.execute(
        "SELECT COUNT(*) FROM effect_gaps WHERE source_type = 'ability' AND used_count > 0"
    ).fetchone()[0]
    skill_total = skill_rows + skill_gaps
    ability_total = ability_rows + ability_gaps
    skill_cov = (skill_rows / skill_total * 100.0) if skill_total else 0.0
    ability_cov = (ability_rows / ability_total * 100.0) if ability_total else 0.0
    print(
        f"  effect coverage  skills: {skill_rows}/{skill_total} ({skill_cov:.1f}%) "
        f"dropped={skill_gaps} used_dropped={skill_used_gaps}"
    )
    print(
        f"  effect coverage  abilities: {ability_rows}/{ability_total} ({ability_cov:.1f}%) "
        f"dropped={ability_gaps} used_dropped={ability_used_gaps}"
    )


def refresh_effect_gap_usage(conn: sqlite3.Connection) -> None:
    conn.execute("UPDATE effect_gaps SET used_count = 0")
    conn.execute(
        """
        UPDATE effect_gaps
        SET used_count = (
            SELECT COUNT(*)
            FROM team_pet_skills tps
            JOIN skills s ON s.id = tps.skill_id
            WHERE s.name = effect_gaps.source_name
        )
        WHERE source_type = 'skill'
        """
    )
    conn.execute(
        """
        UPDATE effect_gaps
        SET used_count = (
            SELECT COUNT(*)
            FROM team_pets tp
            JOIN pets p ON p.id = tp.pet_id
            JOIN abilities a ON a.id = p.ability_id
            WHERE a.name = effect_gaps.source_name
        )
        WHERE source_type = 'ability'
        """
    )


def _require_pak_source(name: str, rows: list[dict]) -> None:
    bad = [
        str(row.get("name", row.get("source_title", "")))
        for row in rows
        if not str(row.get("source_kind", "")).startswith("pak:")
    ]
    if bad:
        raise RuntimeError(f"{name} must be generated from pak data; non-pak rows: {', '.join(bad[:8])}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=DB_DIR / "data.db")
    args = parser.parse_args()

    if not args.db.exists():
        print(f"Database not found: {args.db}")
        print("Run 'python -m roco.data.migrate --reset' first.")
        return

    conn = sqlite3.connect(str(args.db))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")

    print("Importing canonical records...")
    canonical = load_canonical_records()
    skills = list(canonical["skills"])
    abilities = list(canonical["abilities"])
    pets = list(canonical["pets"])
    _require_pak_source("skills.jsonl", skills)
    _require_pak_source("abilities.jsonl", abilities)
    _require_pak_source("pets.jsonl", pets)

    ability_lookup = import_abilities(conn, abilities)
    skill_lookup = import_skills(conn, skills)
    pet_lookup = import_pets(conn, pets, skill_lookup, ability_lookup)

    marks = list(canonical.get("marks", ()))
    if marks:
        _require_pak_source("marks.jsonl", marks)
        import_marks(conn, marks)

    teams = list(canonical.get("teams", ()))
    if teams:
        import_teams(
            conn,
            teams,
            pet_lookup,
            skill_lookup,
        )

    conn.commit()
    for name, in conn.execute(
        "SELECT 'pets' UNION ALL SELECT 'skills' UNION ALL SELECT 'abilities' UNION ALL "
        "SELECT 'pet_skills' UNION ALL SELECT 'skill_effects' UNION ALL SELECT 'ability_effects' UNION ALL "
        "SELECT 'marks' UNION ALL SELECT 'mark_sources' UNION ALL SELECT 'effect_gaps' UNION ALL SELECT 'teams' UNION ALL "
        "SELECT 'team_pets' UNION ALL SELECT 'team_pet_skills'"
    ):
        cnt = conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
        print(f"  {name}: {cnt}")
    conn.close()
    print(f"Done -> {args.db}")


if __name__ == "__main__":
    main()
