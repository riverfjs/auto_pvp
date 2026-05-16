"""Rebuild the normalized SQLite database from parsed structured data."""

from __future__ import annotations

from roco.data.catalog import compile_catalog
from roco.data.import_db import import_abilities, import_pets, import_skills, import_teams, import_yinji
from roco.data.migrate import migrate
from roco.data.utils import PARSED_DIR, DB_DIR, load_json


def main() -> None:
    conn = migrate(reset=True)
    skills = load_json(PARSED_DIR / "skills.json")
    pets = load_json(PARSED_DIR / "pets.json")

    ability_lookup = import_abilities(conn, pets)
    skill_lookup = import_skills(conn, skills)
    pet_lookup = import_pets(conn, pets, skill_lookup, ability_lookup)

    yinji_path = PARSED_DIR / "yinji.json"
    if yinji_path.exists():
        import_yinji(conn, load_json(yinji_path))

    teams_path = PARSED_DIR / "teams.json"
    if teams_path.exists():
        import_teams(conn, load_json(teams_path), pet_lookup, skill_lookup)

    conn.commit()
    catalog = compile_catalog(conn)
    conn.close()
    print(
        f"Built -> {DB_DIR / 'data.db'} "
        f"({len(catalog.pets_by_id)} pets, {len(catalog.skills_by_id)} skills)"
    )


if __name__ == "__main__":
    main()
