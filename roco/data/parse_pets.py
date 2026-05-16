"""Parse raw pet wikitext into a key-value JSON mapping.

Output: _data/parsed/pets.json  →  {"迪莫": {...fields}, "喵喵": {...fields}, ...}

Usage:
    python scripts/parse_pets.py
"""

import re
from roco.data.utils import RAW_DIR, PARSED_DIR, load_json, save_json

TEMPLATE_RE = re.compile(r"^\|(.+?)=(.+)", re.MULTILINE)

LIST_FIELDS = ("技能", "技能解锁等级", "血脉技能", "可学技能石", "图鉴课题", "课题技能石")
INT_FIELDS = ("生命", "物攻", "魔攻", "物防", "魔防", "速度")


def parse_one(name: str, text: str) -> dict | None:
    """Parse a single {{精灵信息}} template. Returns None if malformed."""
    start = text.find("{{精灵信息")
    if start == -1:
        return None
    end = text.find("}}", start)
    if end == -1:
        return None

    pet: dict = {}
    for match in TEMPLATE_RE.finditer(text[start:end]):
        key = match.group(1).strip()
        val = match.group(2).strip()
        pet[key] = val

    for f in LIST_FIELDS:
        raw = pet.get(f, "")
        pet[f] = [v.strip() for v in raw.split(",") if v.strip()] if raw else []

    for f in INT_FIELDS:
        if f in pet:
            try:
                pet[f] = int(pet[f])
            except (ValueError, TypeError):
                pass

    return pet


def main() -> None:
    raw_path = RAW_DIR / "pets_raw.json"
    if not raw_path.exists():
        print(f"Missing {raw_path}. Run fetch_details.py pets first.")
        return

    raw: dict[str, str] = load_json(raw_path)
    pets: dict[str, dict] = {}
    errors: list[str] = []

    for name, wikitext in raw.items():
        pet = parse_one(name, wikitext)
        if pet is None:
            errors.append(name)
        else:
            pets[name] = pet

    out_path = PARSED_DIR / "pets.json"
    save_json(pets, out_path)
    print(f"Parsed {len(pets)} pets → {out_path}")
    if errors:
        print(f"Skipped ({len(errors)}): {', '.join(errors[:10])}")


if __name__ == "__main__":
    main()
