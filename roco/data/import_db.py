"""Load parsed JSON data into the SQLite database.

Reads _data/parsed/{pets,skills,yinji}.json and inserts into _db/data.db.
Run scripts/migrate.py first to create the tables.

Usage:
    python scripts/import_db.py
"""

import json
import sqlite3
from roco.utils import PARSED_DIR, DB_DIR, load_json


def _safe_int(val: str | None) -> int | None:
    try:
        return int(val) if val else None
    except (ValueError, TypeError):
        return None


def import_skills(conn: sqlite3.Connection, skills: dict[str, dict]) -> dict[str, int]:
    """Insert all skills, return {name: id} lookup."""
    lookup: dict[str, int] = {}
    rows: list[tuple] = []
    for name, sk in skills.items():
        rows.append((
            sk.get("技能名称", name),
            sk.get("属性", ""),
            sk.get("技能类别", ""),
            sk.get("耗能", 0),
            sk.get("威力", 0),
            sk.get("效果", ""),
            sk.get("描述", ""),
            sk.get("技能版本", ""),
        ))
    conn.executemany(
        "INSERT INTO skills (name, element, category, energy, power, effect, flavor_text, version) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    # Build lookup
    cur = conn.execute("SELECT id, name FROM skills")
    for row in cur:
        lookup[row[1]] = row[0]
    print(f"  skills: {len(lookup)} inserted")
    return lookup


def import_pets(conn: sqlite3.Connection, pets: dict[str, dict], skill_lookup: dict[str, int]) -> None:
    """Insert all pets and their skill links."""
    pet_rows: list[tuple] = []
    pet_names: list[str] = []
    for name, pet in pets.items():
        pet_names.append(name)
        pet_rows.append((
            name,
            pet.get("地区形态名称", ""),
            pet.get("精灵阶段", ""),
            pet.get("精灵形态", ""),
            pet.get("主属性", ""),
            pet.get("2属性", ""),
            pet.get("特性", ""),
            pet.get("特性描述", ""),
            pet.get("生命", 0),
            pet.get("物攻", 0),
            pet.get("魔攻", 0),
            pet.get("物防", 0),
            pet.get("魔防", 0),
            pet.get("速度", 0),
            pet.get("体型", ""),
            pet.get("重量", ""),
            pet.get("分布地区", ""),
            pet.get("精灵描述", ""),
            1 if pet.get("是否有异色") == "是" else 0,
            pet.get("进化条件", ""),
            pet.get("更新版本", ""),
        ))
    conn.executemany(
        "INSERT INTO pets (name, form_name, stage, form_type, element_primary, element_secondary, "
        "ability_name, ability_desc, hp, atk_phys, atk_mag, def_phys, def_mag, speed, "
        "height, weight, distribution, description, is_shiny, evolution_cond, version) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        pet_rows,
    )

    # Build pet id lookup
    pet_lookup: dict[str, int] = {}
    cur = conn.execute("SELECT id, name FROM pets")
    for row in cur:
        pet_lookup[row[1]] = row[0]

    # Insert pet_skills
    skill_fields = [
        ("技能", "技能"),
        ("血脉技能", "血脉技能"),
        ("可学技能石", "可学技能石"),
    ]
    for field, stype in skill_fields:
        ps_rows: list[tuple] = []
        for name, pet in pets.items():
            names: list[str] = pet.get(field, [])
            levels: list[str] = pet.get("技能解锁等级", []) if field == "技能" else []
            for i, sn in enumerate(names):
                ps_rows.append((
                    pet_lookup[name],
                    skill_lookup.get(sn),
                    sn,
                    stype,
                    _safe_int(levels[i]) if i < len(levels) and levels[i] else None,
                    i,
                ))
        conn.executemany(
            "INSERT INTO pet_skills (pet_id, skill_id, skill_name, skill_type, unlock_level, sort_order) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ps_rows,
        )

    print(f"  pets: {len(pet_lookup)} inserted")
    # Count pet_skills
    cnt = conn.execute("SELECT COUNT(*) FROM pet_skills").fetchone()[0]
    print(f"  pet_skills: {cnt} links inserted")


def import_yinji(conn: sqlite3.Connection, yinji: dict[str, dict]) -> None:
    """Insert all yinji and their skill sources."""
    yinji_rows: list[tuple] = []
    yinji_names: list[str] = []
    for name, yj in yinji.items():
        yinji_names.append(name)
        mechanism = json.dumps(yj.get("机制说明", []), ensure_ascii=False)
        yinji_rows.append((name, yj.get("类型", ""), yj.get("效果描述", ""), mechanism))

    conn.executemany(
        "INSERT INTO yinji (name, type, effect, mechanism) VALUES (?, ?, ?, ?)",
        yinji_rows,
    )

    # Build lookup
    yj_lookup: dict[str, int] = {}
    cur = conn.execute("SELECT id, name FROM yinji")
    for row in cur:
        yj_lookup[row[1]] = row[0]

    # Insert yinji_skills
    ys_rows: list[tuple] = []
    for name, yj in yinji.items():
        yj_id = yj_lookup[name]
        for sk_name, desc in yj.get("可施加技能", {}).items():
            ys_rows.append((yj_id, sk_name, desc))

    conn.executemany(
        "INSERT INTO yinji_skills (yinji_id, skill_name, description) VALUES (?, ?, ?)",
        ys_rows,
    )

    print(f"  yinji: {len(yj_lookup)} inserted")
    cnt = conn.execute("SELECT COUNT(*) FROM yinji_skills").fetchone()[0]
    print(f"  yinji_skills: {cnt} links inserted")


def import_teams(conn: sqlite3.Connection, teams: dict[str, dict]) -> None:
    """Insert all teams and their pet slots."""
    team_rows: list[tuple] = []
    pet_rows: list[tuple] = []

    for tid, team in teams.items():
        team_rows.append((
            tid,
            team.get("title", ""),
            team.get("author", ""),
            team.get("type", ""),
            team.get("bloodline_magic", ""),
            team.get("description", ""),
            team.get("upload_date", ""),
        ))
        for pet in team.get("pets", []):
            moves = pet.get("moves", [])
            pet_rows.append((
                tid,
                pet.get("slot", 0),
                pet.get("name", ""),
                pet.get("name_short", ""),
                pet.get("bloodline", ""),
                pet.get("nature", ""),
                ",".join(pet.get("ivs", [])),
                moves[0] if len(moves) > 0 else "",
                moves[1] if len(moves) > 1 else "",
                moves[2] if len(moves) > 2 else "",
                moves[3] if len(moves) > 3 else "",
            ))

    conn.executemany(
        "INSERT INTO teams (id, title, author, type, bloodline_magic, description, upload_date) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        team_rows,
    )
    conn.executemany(
        "INSERT INTO team_pets (team_id, slot, pet_name, name_short, bloodline, nature, ivs, "
        "move1, move2, move3, move4) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        pet_rows,
    )

    print(f"  teams: {len(team_rows)} inserted")
    print(f"  team_pets: {len(pet_rows)} slots inserted")


def main() -> None:
    db_path = DB_DIR / "data.db"
    if not db_path.exists():
        print(f"Database not found: {db_path}")
        print("Run 'python scripts/migrate.py' first.")
        return

    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")

    print("Importing...")

    skills: dict[str, dict] = load_json(PARSED_DIR / "skills.json")
    skill_lookup = import_skills(conn, skills)

    pets: dict[str, dict] = load_json(PARSED_DIR / "pets.json")
    import_pets(conn, pets, skill_lookup)

    yinji_path = PARSED_DIR / "yinji.json"
    if yinji_path.exists():
        yinji: dict[str, dict] = load_json(yinji_path)
        import_yinji(conn, yinji)

    # Teams
    teams_path = PARSED_DIR / "teams.json"
    if teams_path.exists():
        teams: dict[str, dict] = load_json(teams_path)
        import_teams(conn, teams)

    conn.commit()
    # Summary
    counts = conn.execute(
        "SELECT 'pets', COUNT(*) FROM pets UNION ALL "
        "SELECT 'skills', COUNT(*) FROM skills UNION ALL "
        "SELECT 'pet_skills', COUNT(*) FROM pet_skills UNION ALL "
        "SELECT 'yinji', COUNT(*) FROM yinji UNION ALL "
        "SELECT 'yinji_skills', COUNT(*) FROM yinji_skills UNION ALL "
        "SELECT 'teams', COUNT(*) FROM teams UNION ALL "
        "SELECT 'team_pets', COUNT(*) FROM team_pets"
    ).fetchall()
    for name, cnt in counts:
        print(f"  {name}: {cnt}")

    conn.close()
    print(f"Done → {db_path}")


if __name__ == "__main__":
    main()
