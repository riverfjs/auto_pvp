"""Rebuild SQLite from pak-derived canonical records."""

from __future__ import annotations

import argparse

from roco.data.catalog import compile_catalog
from roco.compiler_v2.artifact import compile_artifacts
from roco.data.canonical import load_canonical_records
from roco.data.import_db import import_abilities, import_marks, import_pets, import_skills, import_teams, print_effect_coverage
from roco.data.migrate import migrate
from roco.data.utils import DB_DIR


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
    parser.add_argument("--allow-used-gaps", action="store_true")
    args = parser.parse_args()

    conn = migrate(reset=True)
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
            fail_used_gaps=not args.allow_used_gaps,
        )

    conn.commit()
    print_effect_coverage(conn)
    catalog = compile_catalog(conn)
    conn.close()
    hot_path, debug_path = compile_artifacts(DB_DIR / "data.db")
    print(
        f"Built -> {DB_DIR / 'data.db'} "
        f"({len(catalog.pets_by_id)} pets, {len(catalog.skills_by_id)} skills, "
        f"{len(catalog.unsupported_effect_stats)} gap groups)"
    )
    print(f"Compiled kernel catalogs -> {hot_path}, {debug_path}")


if __name__ == "__main__":
    main()
