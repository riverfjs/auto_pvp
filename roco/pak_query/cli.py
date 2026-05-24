"""CLI for querying extracted pak pet/skill/ability learn data."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from roco.data.parse_pak import DEFAULT_PAK_DATA_DIR
from roco.pak_query.index import PakLookup, LearnLink, SkillItemSource


def _json_default(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, set):
        return sorted(value)
    raise TypeError(f"{type(value).__name__} is not JSON serializable")


def _skill_name(index: PakLookup, link: LearnLink) -> str:
    skill = index.skills.get(link.skill_id)
    return link.skill_name_hint or (skill.name if skill else str(link.skill_id))


def _print_skill_link(index: PakLookup, link: LearnLink, *, prefix: str = "  ") -> None:
    name = _skill_name(index, link)
    parts = [f"{name} ({link.skill_id})", link.source_label]
    if link.source_type == "base" and link.level_point is not None:
        parts.append(f"Lv{link.level_point}")
    if link.source_type == "bloodline":
        if link.bloodline:
            parts.append(link.bloodline)
        if link.level_point is not None:
            parts.append(f"血脉Lv{link.level_point}")
    print(prefix + " | ".join(parts))


def _print_item_sources(sources: tuple[SkillItemSource, ...], *, prefix: str = "    ") -> None:
    for source in sources:
        print(f"{prefix}{source.item_name} ({source.item_id})")
        for text in source.acquire:
            print(f"{prefix}  获取: {text}")
        for topic in source.handbook:
            pet = topic.get("handbook_pet", "")
            desc = topic.get("topic_desc", "")
            if pet or desc:
                print(f"{prefix}  图鉴: {pet} - {desc}")


def _print_pet_reports(index: PakLookup, reports: list[dict[str, Any]]) -> int:
    if not reports:
        print("未找到精灵")
        return 1
    for report in reports:
        pet = report["pet"]
        print(f"精灵 {pet.name} ({pet.id})")
        if report["abilities"]:
            print("特性:")
            for ability in report["abilities"]:
                print(f"  {ability.name} ({ability.id}) - {ability.description}")
        for title, key in (
            ("基础技能", "base_skills"),
            ("血脉技能", "bloodline_skills"),
            ("技能石技能", "stone_skills"),
            ("传说技能", "legendary_skills"),
        ):
            links = report[key]
            print(f"{title}:")
            if not links:
                print("  无")
                continue
            for link in links:
                _print_skill_link(index, link)
                if link.source_type == "stone" and link.item_sources:
                    _print_item_sources(link.item_sources)
    return 0


def _print_skill_reports(index: PakLookup, reports: list[dict[str, Any]]) -> int:
    if not reports:
        print("未找到技能")
        return 1
    for report in reports:
        skill = report["skill"]
        print(f"技能 {skill.name} ({skill.id})")
        if skill.description:
            print(f"描述: {skill.description}")
        if report["item_sources"]:
            print("技能石来源:")
            _print_item_sources(report["item_sources"], prefix="  ")
        learners = report["learners"]
        print(f"可学习精灵: {len(learners)}")
        for link in sorted(learners, key=lambda item: (item.source_type, item.pet_id)):
            pet = index.pets.get(link.pet_id)
            pet_text = f"{pet.name} ({pet.id})" if pet else str(link.pet_id)
            suffix: list[str] = [link.source_label]
            if link.source_type == "base" and link.level_point is not None:
                suffix.append(f"Lv{link.level_point}")
            if link.source_type == "bloodline":
                if link.bloodline:
                    suffix.append(link.bloodline)
                if link.level_point is not None:
                    suffix.append(f"血脉Lv{link.level_point}")
            print(f"  {pet_text} | {' | '.join(suffix)}")
            if link.source_type == "stone" and link.item_sources:
                _print_item_sources(link.item_sources, prefix="    ")
    return 0


def _print_ability_reports(index: PakLookup, reports: list[dict[str, Any]]) -> int:
    if not reports:
        print("未找到特性")
        return 1
    for report in reports:
        ability = report["ability"]
        print(f"特性 {ability.name} ({ability.id})")
        if ability.description:
            print(f"描述: {ability.description}")
        owners = report["owners"]
        grouped: dict[int, list[str]] = {}
        for owner in owners:
            grouped.setdefault(owner.pet_id, []).append(owner.field)
        print(f"所属精灵: {len(grouped)}")
        for pet_id, fields in sorted(grouped.items()):
            owner = next(item for item in owners if item.pet_id == pet_id)
            pet = index.pets.get(owner.pet_id)
            pet_text = f"{pet.name} ({pet.id})" if pet else str(owner.pet_id)
            print(f"  {pet_text} | {', '.join(sorted(set(fields)))}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Query extracted pak pet/skill/ability data")
    parser.add_argument("--pak-dir", type=Path, default=DEFAULT_PAK_DATA_DIR)
    parser.add_argument("--json", action="store_true", help="print structured JSON")
    sub = parser.add_subparsers(dest="command", required=True)

    pet = sub.add_parser("pet", help="query learnable skills and abilities for a pet")
    pet.add_argument("query")

    skill = sub.add_parser("skill", help="query which pets can learn a skill")
    skill.add_argument("query")

    ability = sub.add_parser("ability", help="query which pets own an ability")
    ability.add_argument("query")

    args = parser.parse_args(argv)
    index = PakLookup(args.pak_dir)

    if args.command == "pet":
        reports = index.pet_report(args.query)
        if args.json:
            print(json.dumps(reports, ensure_ascii=False, indent=2, default=_json_default))
            return 0 if reports else 1
        return _print_pet_reports(index, reports)
    if args.command == "skill":
        reports = index.skill_report(args.query)
        if args.json:
            print(json.dumps(reports, ensure_ascii=False, indent=2, default=_json_default))
            return 0 if reports else 1
        return _print_skill_reports(index, reports)
    if args.command == "ability":
        reports = index.ability_report(args.query)
        if args.json:
            print(json.dumps(reports, ensure_ascii=False, indent=2, default=_json_default))
            return 0 if reports else 1
        return _print_ability_reports(index, reports)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
