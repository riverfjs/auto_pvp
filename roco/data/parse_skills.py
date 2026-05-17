"""Parse raw skill wikitext into canonical skill JSONL records.

Output: _data/canonical/skills.jsonl

Usage:
    python scripts/parse_skills.py
"""

import argparse
import re
from typing import Any

from roco.data.effect_classifier import classify_skill_record, load_manual_rules
from roco.data.utils import CANONICAL_DIR, RAW_DIR, iter_jsonl, with_canonical_hash, write_jsonl

TEMPLATE_RE = re.compile(r"^\|(.+?)=(.+)", re.MULTILINE)
INT_FIELDS = ("耗能", "威力")


def parse_one(name: str, text: str, manual_rules: dict[str, dict[str, Any]] | None = None) -> dict | None:
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

    record = {
        "kind": "skill",
        "name": skill.get("技能名称", name),
        "element": skill.get("属性", "普通"),
        "category": skill.get("技能类别", "物攻"),
        "energy": skill.get("耗能", 0),
        "power": skill.get("威力", 0),
        "effect_text": skill.get("效果", ""),
        "flavor_text": skill.get("描述", ""),
        "source_version": skill.get("技能版本", ""),
        "source_fields": skill,
    }
    result = classify_skill_record(record, manual_rules)
    record["flags"] = result.flags
    record["effects"] = list(result.effects)
    record["classification"] = result.meta()
    return record


def _canonical_key(row: dict) -> str:
    return str(row.get("source_title") or row.get("name", ""))


def _existing_canonical(path) -> dict[str, dict]:
    if not path.exists():
        return {}
    return {_canonical_key(row): row for row in iter_jsonl(path)}


def _keep_existing(existing: dict[str, dict], row: dict, *, force: bool) -> dict | None:
    key = str(row.get("source_title") or row.get("name", ""))
    previous = existing.get(key)
    if (
        previous is not None
        and not force
        and previous.get("canonical_hash")
        and previous.get("source_hash")
        and previous.get("source_hash") == row.get("source_hash")
        and previous.get("missing_from_index") == row.get("missing_from_index")
    ):
        return previous
    return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    raw_path = RAW_DIR / "skills_raw.jsonl"
    if not raw_path.exists():
        print(f"Missing {raw_path}. Run fetch_details.py skills first.")
        return

    out_path = CANONICAL_DIR / "skills.jsonl"
    existing = _existing_canonical(out_path)
    manual_rules = load_manual_rules("skill")
    skills: list[dict] = []
    errors: list[str] = []

    for row in iter_jsonl(raw_path):
        if row.get("missing_source_page"):
            errors.append(str(row.get("name", "")))
            continue
        kept = _keep_existing(existing, row, force=args.force)
        if kept is not None:
            skills.append(kept)
            continue
        name = str(row.get("name", ""))
        sk = parse_one(name, str(row.get("raw_text", "")), manual_rules)
        if sk is None:
            errors.append(name)
        else:
            skills.append(with_canonical_hash(sk, row))

    count = write_jsonl(skills, out_path)
    print(f"Parsed {count} skills -> {out_path}")
    if errors:
        print(f"Skipped ({len(errors)}): {', '.join(errors[:10])}")


if __name__ == "__main__":
    main()
