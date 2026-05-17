"""Parse raw pet wikitext into canonical pet and ability JSONL records.

Output:
  _data/canonical/pets.jsonl
  _data/canonical/abilities.jsonl

Usage:
    python scripts/parse_pets.py
"""

import argparse
import re
from typing import Any

from roco.data.effect_classifier import classify_ability_record, load_manual_rules
from roco.data.utils import CANONICAL_DIR, RAW_DIR, content_hash, iter_jsonl, with_canonical_hash, write_jsonl

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

    skill_links: list[dict[str, Any]] = []
    for field, source_type in (("技能", "技能"), ("血脉技能", "血脉技能"), ("可学技能石", "可学技能石")):
        levels: list[str] = pet.get("技能解锁等级", []) if field == "技能" else []
        for i, skill_name in enumerate(pet.get(field, [])):
            skill_links.append({
                "name": skill_name,
                "source_type": source_type,
                "unlock_level": _safe_int(levels[i]) if i < len(levels) else None,
                "sort_order": len(skill_links),
            })

    return {
        "kind": "pet",
        "name": name,
        "display_name": pet.get("精灵名称", name),
        "form_name": pet.get("地区形态名称", ""),
        "stage": pet.get("精灵阶段", ""),
        "form_type": pet.get("精灵形态", ""),
        "lineage_key": _lineage_key(pet.get("精灵初阶名称", name)),
        "elements": [pet.get("主属性", "普通"), pet.get("2属性", "")],
        "ability": pet.get("特性", "").strip(),
        "ability_description": pet.get("特性描述", "").strip(),
        "stats": {
            "hp": _safe_int(pet.get("生命")) or 1,
            "atk_phys": _safe_int(pet.get("物攻")) or 0,
            "atk_mag": _safe_int(pet.get("魔攻")) or 0,
            "def_phys": _safe_int(pet.get("物防")) or 0,
            "def_mag": _safe_int(pet.get("魔防")) or 0,
            "speed": _safe_int(pet.get("速度")) or 0,
        },
        "height": pet.get("体型", ""),
        "weight": pet.get("重量", ""),
        "distribution": pet.get("分布地区", ""),
        "description": pet.get("精灵描述", ""),
        "is_shiny": pet.get("是否有异色") == "是",
        "evolution_cond": pet.get("进化条件", ""),
        "source_version": pet.get("更新版本", ""),
        "skills": skill_links,
        "source_fields": pet,
    }


def _ability_record(name: str, description: str, manual_rules: dict[str, dict[str, Any]]) -> dict:
    record = {
        "kind": "ability",
        "name": name,
        "description": description,
        "source_version": "",
    }
    result = classify_ability_record(record, manual_rules)
    record["flags"] = result.flags
    record["effects"] = list(result.effects)
    record["classification"] = result.meta()
    return record


def _ability_source(name: str, description: str) -> dict:
    return {
        "source_hash": content_hash({"name": name, "description": description}),
        "source_title": name,
        "source_kind": "ability",
    }


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
        and "ability_description" in previous
        and "lineage_key" in previous
        and previous.get("canonical_hash")
        and previous.get("source_hash")
        and previous.get("source_hash") == row.get("source_hash")
        and previous.get("missing_from_index") == row.get("missing_from_index")
    ):
        return previous
    return None


def _keep_existing_ability(existing: dict[str, dict], source: dict, *, force: bool) -> dict | None:
    previous = existing.get(str(source.get("source_title", "")))
    if (
        previous is not None
        and not force
        and previous.get("canonical_hash")
        and previous.get("source_hash") == source.get("source_hash")
    ):
        return previous
    return None


def _safe_int(val: object) -> int | None:
    try:
        if val is None or val == "":
            return None
        return int(val)
    except (ValueError, TypeError):
        return None


def _lineage_key(raw: object) -> str:
    text = str(raw or "").strip()
    text = re.sub(r"[（(][^）)]*[）)]", "", text)
    return re.sub(r"\s+", "", text).strip()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    raw_path = RAW_DIR / "pets_raw.jsonl"
    if not raw_path.exists():
        print(f"Missing {raw_path}. Run fetch_details.py pets first.")
        return

    pets_path = CANONICAL_DIR / "pets.jsonl"
    abilities_path = CANONICAL_DIR / "abilities.jsonl"
    existing_pets = _existing_canonical(pets_path)
    existing_abilities = _existing_canonical(abilities_path)
    pets: list[dict] = []
    abilities: dict[str, dict] = {}
    manual_rules = load_manual_rules("ability")
    errors: list[str] = []

    for row in iter_jsonl(raw_path):
        if row.get("missing_source_page"):
            errors.append(str(row.get("name", "")))
            continue
        kept = _keep_existing(existing_pets, row, force=args.force)
        if kept is not None:
            pets.append(kept)
            raw_fields = kept.get("source_fields", {})
        else:
            raw_fields = {}
            name = str(row.get("name", ""))
            pet = parse_one(name, str(row.get("raw_text", "")))
            if pet is None:
                errors.append(name)
                continue
            pet = with_canonical_hash(pet, row)
            pets.append(pet)
            raw_fields = pet.get("source_fields", {})

        ability_name = str(raw_fields.get("特性", "")).strip()
        if ability_name and ability_name not in abilities:
            description = str(raw_fields.get("特性描述", ""))
            source = _ability_source(ability_name, description)
            ability = _keep_existing_ability(existing_abilities, source, force=args.force)
            if ability is None:
                ability = with_canonical_hash(_ability_record(ability_name, description, manual_rules), source)
            abilities[ability_name] = ability

    pet_count = write_jsonl(pets, pets_path)
    ability_count = write_jsonl((abilities[name] for name in sorted(abilities)), abilities_path)
    print(f"Parsed {pet_count} pets -> {pets_path}")
    print(f"Parsed {ability_count} abilities -> {abilities_path}")
    if errors:
        print(f"Skipped ({len(errors)}): {', '.join(errors[:10])}")


if __name__ == "__main__":
    main()
