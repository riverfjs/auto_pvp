"""Parse raw skill wikitext → classified JSON with tags and pre-parsed fields.

Output: _data/parsed/skills.json  →  {"猛烈撞击": {..., "tags": [...], ...}}

Usage:
    python scripts/parse_skills.py
"""

import re
from roco.data.utils import RAW_DIR, PARSED_DIR, load_json, save_json
from roco.engine.skill_tags import classify
from roco.engine.state import SkillRef

TEMPLATE_RE = re.compile(r"^\|(.+?)=(.+)", re.MULTILINE)
INT_FIELDS = ("耗能", "威力")


def parse_one(name: str, text: str) -> dict | None:
    start = text.find("{{技能信息")
    if start == -1:
        return None
    end = text.find("}}", start)
    if end == -1:
        return None

    skill: dict = {}
    for match in TEMPLATE_RE.finditer(text[start:end]):
        key = match.group(1).strip()
        val = match.group(2).strip()
        skill[key] = val

    for f in INT_FIELDS:
        if f in skill:
            try:
                skill[f] = int(skill[f])
            except (ValueError, TypeError):
                pass

    # Classify at parse time — store tags + parsed fields in JSON
    sref = SkillRef(
        name=skill.get("技能名称", name),
        element=skill.get("属性", ""),
        category=skill.get("技能类别", ""),
        energy=skill.get("耗能", 0),
        power=skill.get("威力", 0),
        effect=skill.get("效果", ""),
    )
    classify(sref)
    skill["tags"] = sref.tags
    skill["weather_type"] = sref.weather_type
    skill["enemy_cost_up_amount"] = sref.enemy_cost_up_amount
    skill["hp_cost_pct"] = sref.hp_cost_pct
    skill["permanent_hit_growth"] = sref.permanent_hit_growth
    skill["permanent_power_growth"] = sref.permanent_power_growth

    return skill


def main() -> None:
    raw_path = RAW_DIR / "skills_raw.json"
    if not raw_path.exists():
        print(f"Missing {raw_path}. Run fetch_details.py skills first.")
        return

    raw: dict[str, str] = load_json(raw_path)
    skills: dict[str, dict] = {}
    errors: list[str] = []

    for name, wikitext in raw.items():
        sk = parse_one(name, wikitext)
        if sk is None:
            errors.append(name)
        else:
            skills[name] = sk

    out_path = PARSED_DIR / "skills.json"
    save_json(skills, out_path)
    print(f"Parsed {len(skills)} skills → {out_path}")
    if errors:
        print(f"Skipped ({len(errors)}): {', '.join(errors[:10])}")


if __name__ == "__main__":
    main()
