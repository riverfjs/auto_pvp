"""Build canonical records in memory from pak and raw team inputs."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from roco.compiler_v2.effect_codegen import PakTables
from roco.data.parse_pak import (
    DEFAULT_PAK_DATA_DIR,
    PakData,
    _desc_notes,
    build_abilities,
    build_marks,
    build_pets,
    build_skills,
)
from roco.data.parse_teams import build_teams_from_raw


@lru_cache(maxsize=4)
def load_canonical_records(
    pak_dir: str | Path = DEFAULT_PAK_DATA_DIR,
) -> dict[str, tuple[dict, ...]]:
    """Return pak-derived canonical records without writing JSONL files."""

    root = Path(pak_dir)
    data = PakData(root)
    pak_tables = PakTables(root)
    desc_notes = _desc_notes(data.desc_note_conf)

    skills, skill_names_by_id = build_skills(data, desc_notes, pak_tables)
    abilities, ability_name_by_feature_id = build_abilities(data, desc_notes, pak_tables)
    pets = build_pets(data, ability_name_by_feature_id, skill_names_by_id)
    marks = build_marks(data, desc_notes)
    teams = build_teams_from_raw()

    return {
        "skills": tuple(skills),
        "abilities": tuple(abilities),
        "pets": tuple(pets),
        "marks": tuple(marks),
        "teams": tuple(teams),
    }


def canonical_list(name: str, pak_dir: str | Path = DEFAULT_PAK_DATA_DIR) -> list[dict]:
    """Return one canonical collection by file-style name or bare key."""

    key = name.removesuffix(".jsonl")
    return [dict(row) for row in load_canonical_records(pak_dir).get(key, ())]
