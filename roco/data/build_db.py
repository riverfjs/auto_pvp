"""Rebuild SQLite from pak-derived canonical records."""

from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

from roco.data.catalog import compile_catalog
from roco.compiler_v2.catalog_compiler import compile_catalogs
from roco.data.canonical import load_canonical_records
from roco.data.import_db import (
    import_abilities,
    import_marks,
    import_pets,
    import_skills,
    import_teams,
    print_effect_coverage,
)
from roco.data.migrate import migrate
from roco.data.utils import DB_DIR


TARGET_DB = DB_DIR / "data.db"


def _sqlite_sidecars(path: Path) -> tuple[Path, Path]:
    return (
        path.with_name(path.name + "-wal"),
        path.with_name(path.name + "-shm"),
    )


def _cleanup_db_files(path: Path) -> None:
    path.unlink(missing_ok=True)
    for sidecar in _sqlite_sidecars(path):
        sidecar.unlink(missing_ok=True)


def _new_temp_db_path() -> Path:
    DB_DIR.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        prefix=".data-build-",
        suffix=".db",
        dir=DB_DIR,
        delete=False,
    )
    handle.close()
    return Path(handle.name)


def _publish_db(tmp_db: Path, target_db: Path) -> None:
    for sidecar in _sqlite_sidecars(target_db):
        sidecar.unlink(missing_ok=True)
    tmp_db.replace(target_db)
    for sidecar in _sqlite_sidecars(tmp_db):
        sidecar.unlink(missing_ok=True)


def _require_pak_source(name: str, rows: list[dict]) -> None:
    bad = [
        str(row.get("name", row.get("source_title", "")))
        for row in rows
        if not str(row.get("source_kind", "")).startswith("pak:")
    ]
    if bad:
        raise RuntimeError(
            f"{name} must be generated from pak data; "
            f"non-pak rows: {', '.join(bad[:8])}"
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.parse_args()

    tmp_db = _new_temp_db_path()
    conn = None
    try:
        conn = migrate(reset=True, db_path=tmp_db)
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
        print_effect_coverage(conn)
        catalog = compile_catalog(conn)
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.close()
        conn = None
        _publish_db(tmp_db, TARGET_DB)
    except Exception:
        if conn is not None:
            try:
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            except Exception:
                pass
            conn.close()
        _cleanup_db_files(tmp_db)
        raise

    hot_path, debug_path = compile_catalogs(TARGET_DB)
    print(
        f"Built -> {TARGET_DB} "
        f"({len(catalog.pets_by_id)} pets, {len(catalog.skills_by_id)} skills, "
        f"{len(catalog.unsupported_effect_stats)} gap groups)"
    )
    print(f"Compiled kernel catalogs -> {hot_path}, {debug_path}")


if __name__ == "__main__":
    main()
