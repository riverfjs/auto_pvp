"""Import canonical JSONL records into the normalized SQLite data store."""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from roco.data.utils import CANONICAL_DIR, DB_DIR, load_jsonl
from roco.engine.effect_model import EffectTag, Timing
from roco.engine.effect_registry import IMPLEMENTED_EFFECT_TAGS
from roco.engine.state import SkillCategory, normalize_element_name


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

MARK_TAG_BY_CODE = {
    "poison": EffectTag.POISON_MARK,
    "moisture": EffectTag.MOISTURE_MARK,
    "dragon": EffectTag.DRAGON_MARK,
    "wind": EffectTag.WIND_MARK,
    "charge": EffectTag.CHARGE_MARK,
    "solar": EffectTag.SOLAR_MARK,
    "attack": EffectTag.ATTACK_MARK,
    "slow": EffectTag.SLOW_MARK,
    "sluggish": EffectTag.SLUGGISH_MARK,
    "spirit": EffectTag.SPIRIT_MARK,
    "meteor": EffectTag.METEOR_MARK,
    "thorn": EffectTag.THORN_MARK,
    "momentum": EffectTag.MOMENTUM_MARK,
}


def _parse_timing(raw: object) -> Timing | None:
    if raw is None:
        return None
    if isinstance(raw, Timing):
        return raw
    if isinstance(raw, int):
        try:
            return Timing(raw)
        except ValueError:
            return None
    if isinstance(raw, str):
        try:
            return Timing[raw]
        except KeyError:
            return None
    return None


def _parse_tag(raw: object) -> EffectTag | None:
    if isinstance(raw, EffectTag):
        return raw
    if isinstance(raw, int):
        try:
            return EffectTag(raw)
        except ValueError:
            return None
    if isinstance(raw, str):
        try:
            return EffectTag[raw]
        except KeyError:
            return None
    return None


def _gap_row(
    source_type: str,
    source_name: str,
    primitive: str,
    timing: Timing | None,
    params: Mapping[str, Any] | None,
    reason: str,
) -> tuple:
    return (
        source_type,
        source_name,
        primitive,
        timing.value if timing is not None else None,
        _json(dict(params or {})),
        reason,
        0,
    )


def _classification_gaps(source_type: str, record: Record) -> list[tuple]:
    name = str(record.get("name", ""))
    classification = record.get("classification") or {}
    rows: list[tuple] = []
    for gap in classification.get("gaps", ()) if isinstance(classification, Mapping) else ():
        timing = _parse_timing(gap.get("timing"))
        rows.append(_gap_row(
            source_type,
            name,
            str(gap.get("primitive", name)),
            timing,
            gap.get("params", {}),
            str(gap.get("reason", "needs_manual")),
        ))
    return rows


def _effect_rows(
    *,
    owner_id: int,
    source_type: str,
    source_name: str,
    effects: Iterable[Mapping[str, Any]],
    default_flags: int,
) -> tuple[list[tuple], list[tuple]]:
    rows: list[tuple] = []
    gaps: list[tuple] = []
    for order, raw in enumerate(effects):
        timing = _parse_timing(raw.get("timing"))
        tag = _parse_tag(raw.get("tag"))
        params = dict(raw.get("params", {}) or {})
        condition = str(raw.get("condition", "") or "")
        sort_order = int(raw.get("sort_order", order))
        if timing is None:
            gaps.append(_gap_row(source_type, source_name, str(raw.get("timing", "")), None, params, "timing_not_defined"))
            continue
        if tag is None:
            gaps.append(_gap_row(source_type, source_name, str(raw.get("tag", "")), timing, params, "effect_tag_not_defined"))
            continue
        if tag not in IMPLEMENTED_EFFECT_TAGS:
            gaps.append(_gap_row(source_type, source_name, tag.name, timing, params, "runtime_handler_missing"))
            continue
        rows.append((owner_id, timing.value, tag.value, int(raw.get("flags", default_flags)), _json(params), condition, sort_order))
    return rows, gaps


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
    for record in records:
        name = str(record.get("name", "")).strip()
        if not name:
            continue
        built, gaps = _effect_rows(
            owner_id=lookup[name],
            source_type="ability",
            source_name=name,
            effects=record.get("effects", ()) or (),
            default_flags=_required_int(record.get("flags"), 0),
        )
        effect_rows.extend(built)
        gap_rows.extend(gaps)
        gap_rows.extend(_classification_gaps("ability", record))
    if effect_rows:
        conn.executemany(
            "INSERT INTO ability_effects (ability_id, timing_code, tag_code, flags, params_json, condition, sort_order) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            effect_rows,
        )
    inserted_gaps = _insert_gaps(conn, gap_rows)
    print(f"  abilities: {len(lookup)} inserted")
    print(f"  ability_effects: {len(effect_rows)} inserted")
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
            _required_int(record.get("energy"), 0),
            _required_int(record.get("power"), 0),
            str(record.get("effect_text", "")),
            str(record.get("flavor_text", "")),
            _required_int(record.get("flags"), 0),
            str(record.get("source_version", "")),
        ))
    conn.executemany(
        "INSERT INTO skills (name, element_id, category_code, category_name, energy, power, effect_text, flavor_text, flags, source_version) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    lookup = {name: sid for sid, name in conn.execute("SELECT id, name FROM skills")}
    effect_rows: list[tuple] = []
    gap_rows: list[tuple] = []
    for record in records:
        name = str(record["name"])
        built, gaps = _effect_rows(
            owner_id=lookup[name],
            source_type="skill",
            source_name=name,
            effects=record.get("effects", ()) or (),
            default_flags=_required_int(record.get("flags"), 0),
        )
        effect_rows.extend(built)
        gap_rows.extend(gaps)
        gap_rows.extend(_classification_gaps("skill", record))
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
        rows.append((
            str(record["name"]),
            str(record.get("form_name", "")),
            str(record.get("stage", "")),
            str(record.get("form_type", "")),
            _element_id(conn, str(elements[0] or "普通")),
            _maybe_element_id(conn, str(elements[1] or "")),
            ability_lookup.get(ability_name),
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
        "INSERT INTO pets (name, form_name, stage, form_type, element_primary_id, element_secondary_id, ability_id, "
        "hp, atk_phys, atk_mag, def_phys, def_mag, speed, height, weight, distribution, description, is_shiny, evolution_cond, source_version) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
    print(f"  pets: {len(pet_lookup)} inserted")
    print(f"  pet_skills: {len(link_rows)} links inserted")
    return pet_lookup


def import_marks(conn: sqlite3.Connection, marks: Iterable[Record]) -> None:
    records = _records(marks, "mark")
    skill_lookup = {name: sid for sid, name in conn.execute("SELECT id, name FROM skills")}
    mark_rows: list[tuple] = []
    source_rows: list[tuple] = []
    gap_rows: list[tuple] = []
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
        tag = MARK_TAG_BY_CODE.get(code)
        for source in record.get("source_skills", ()) or ():
            skill_name = str(source.get("skill", "")).strip()
            sid = skill_lookup.get(skill_name)
            source_rows.append((
                mark_lookup[code],
                skill_name,
                str(source.get("description", "")),
            ))
            if not sid or tag is None:
                continue
            exists = conn.execute(
                "SELECT 1 FROM skill_effects WHERE skill_id = ? AND tag_code = ? LIMIT 1",
                (sid, tag.value),
            ).fetchone()
            if exists is None:
                gap_rows.append(_gap_row(
                    "skill",
                    skill_name,
                    tag.name,
                    None,
                    {"mark": code, "description": source.get("description", "")},
                    "mark_source_missing_effect",
                ))
    if source_rows:
        conn.executemany(
            "INSERT OR IGNORE INTO mark_sources (mark_id, skill_name, description) VALUES (?, ?, ?)",
            source_rows,
        )
    inserted_gaps = _insert_gaps(conn, gap_rows)
    print(f"  marks: {len(mark_rows)} upserted")
    print(f"  mark_sources: {len(source_rows)} inserted")
    print(f"  mark audit effect_gaps: {inserted_gaps} inserted")


def import_teams(
    conn: sqlite3.Connection,
    teams: Iterable[Record],
    pet_lookup: dict[str, int],
    skill_lookup: dict[str, int],
    *,
    fail_used_gaps: bool = True,
) -> None:
    records = _records(teams, "team")
    team_rows: list[tuple] = []
    pet_rows: list[tuple] = []
    skill_rows: list[tuple] = []

    for team in records:
        team_rows.append((
            str(team.get("id", "")),
            str(team.get("title", "")),
            str(team.get("author", "")),
            str(team.get("type", "")),
            str(team.get("bloodline_magic", "")),
            str(team.get("description", "")),
            str(team.get("upload_date", "")),
        ))
    conn.executemany(
        "INSERT INTO teams (id, title, author, team_type, bloodline_magic, description, upload_date) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
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
                str(pet.get("nature", "")),
                _json(pet.get("ivs", [])),
            ))
    conn.executemany(
        "INSERT INTO team_pets (team_id, slot, pet_id, pet_name, name_short, bloodline, nature, ivs_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
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
    if fail_used_gaps:
        assert_no_blocking_effect_gaps(conn)
    print(f"  teams: {len(team_rows)} inserted")
    print(f"  team_pets: {len(pet_rows)} slots inserted")
    print(f"  team_pet_skills: {len(skill_rows)} moves inserted")


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


def assert_no_blocking_effect_gaps(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        """
        SELECT source_type, source_name, primitive, reason, used_count
        FROM effect_gaps
        WHERE used_count > 0
        ORDER BY used_count DESC, source_type, source_name
        LIMIT 20
        """
    ).fetchall()
    if not rows:
        return
    details = ", ".join(f"{row[0]}:{row[1]} used={row[4]} reason={row[3]}" for row in rows)
    raise RuntimeError(f"used skills/abilities have unclassified effect gaps: {details}")


def _load_required(name: str) -> list[dict]:
    path = CANONICAL_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"Missing canonical data file: {path}")
    return load_jsonl(path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=DB_DIR / "data.db")
    parser.add_argument("--allow-used-gaps", action="store_true")
    args = parser.parse_args()

    if not args.db.exists():
        print(f"Database not found: {args.db}")
        print("Run 'python -m roco.data.migrate --reset' first.")
        return

    conn = sqlite3.connect(str(args.db))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")

    print("Importing canonical JSONL...")
    skills = _load_required("skills.jsonl")
    abilities = _load_required("abilities.jsonl")
    pets = _load_required("pets.jsonl")

    ability_lookup = import_abilities(conn, abilities)
    skill_lookup = import_skills(conn, skills)
    pet_lookup = import_pets(conn, pets, skill_lookup, ability_lookup)

    marks_path = CANONICAL_DIR / "marks.jsonl"
    if marks_path.exists():
        import_marks(conn, load_jsonl(marks_path))

    teams_path = CANONICAL_DIR / "teams.jsonl"
    if teams_path.exists():
        import_teams(
            conn,
            load_jsonl(teams_path),
            pet_lookup,
            skill_lookup,
            fail_used_gaps=not args.allow_used_gaps,
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
