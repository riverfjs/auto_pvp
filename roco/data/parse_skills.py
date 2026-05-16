"""Parse raw skill wikitext into a key-value JSON mapping.

Output: _data/parsed/skills.json  →  {"猛烈撞击": {...fields}, ...}

Usage:
    python scripts/parse_skills.py
"""

import re
from roco.utils import RAW_DIR, PARSED_DIR, load_json, save_json

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
