"""Merge parsed pets, skills & yinji into the final PVP database.

Output: _db/pvp_db.json

Usage:
    python scripts/build_db.py
"""

from scripts.utils import PARSED_DIR, DB_DIR, load_json, save_json


def main() -> None:
    pets_path = PARSED_DIR / "pets.json"
    skills_path = PARSED_DIR / "skills.json"
    yinji_path = PARSED_DIR / "yinji.json"

    if not pets_path.exists():
        print(f"Missing {pets_path}. Run parse_pets.py first.")
        return
    if not skills_path.exists():
        print(f"Missing {skills_path}. Run parse_skills.py first.")
        return

    pets: dict[str, dict] = load_json(pets_path)
    skills: dict[str, dict] = load_json(skills_path)
    yinji: dict[str, dict] = load_json(yinji_path) if yinji_path.exists() else {}
    print(f"Loaded {len(pets)} pets, {len(skills)} skills, {len(yinji)} 印记")

    # Resolve skill references in each pet
    skill_fields = ("技能", "血脉技能", "可学技能石")
    missing_skills: set[str] = set()

    for name, pet in pets.items():
        for field in skill_fields:
            skill_names: list[str] = pet.get(field, [])
            if not skill_names:
                continue
            resolved = {}
            for sn in skill_names:
                if sn in skills:
                    resolved[sn] = skills[sn]
                elif sn in yinji:  # 印记 sometimes referenced as skills
                    pass  # skip, they're marks
                else:
                    missing_skills.add(sn)
            if resolved:
                pet[f"_{field}"] = resolved

    db = {
        "meta": {
            "source": "https://wiki.biligame.com/rocom",
            "license": "CC BY-NC-SA 4.0",
            "pet_count": len(pets),
            "skill_count": len(skills),
            "yinji_count": len(yinji),
        },
        "pets": pets,
        "skills": skills,
        "yinji": yinji,
    }

    out_path = DB_DIR / "pvp_db.json"
    save_json(db, out_path)
    print(f"Built → {out_path}")
    if missing_skills:
        print(f"Unresolved skills ({len(missing_skills)}): {', '.join(sorted(missing_skills)[:20])}")


if __name__ == "__main__":
    main()
