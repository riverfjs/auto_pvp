"""Read-only lookup indexes over extracted pak data."""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from roco.data.parse_pak import (
    DEFAULT_PAK_DATA_DIR,
    PakData,
    _clean_desc,
    _desc_notes,
    _int,
    _pet_display_name,
    _skill_record,
)

LEARN_SKILL_ACTION = 13


@dataclass(frozen=True, slots=True)
class SkillInfo:
    id: int
    name: str
    description: str
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PetInfo:
    id: int
    name: str
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AbilityInfo:
    id: int
    name: str
    description: str
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SkillItemSource:
    item_id: int
    item_name: str
    item_description: str
    acquire: tuple[str, ...] = ()
    handbook: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True, slots=True)
class LearnLink:
    pet_id: int
    skill_id: int
    source_type: str
    source_label: str
    level_point: int | None = None
    stage: int | None = None
    bloodline: str = ""
    skill_name_hint: str = ""
    item_sources: tuple[SkillItemSource, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class AbilityOwner:
    pet_id: int
    ability_id: int
    field: str


def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as fp:
        return json.load(fp)


def _table(root: Path, rel: str) -> dict[str, dict[str, Any]]:
    data = _load_json(root / rel)
    rows = data.get("RocoDataRows") if isinstance(data, dict) else None
    if isinstance(rows, dict):
        return rows
    raise ValueError(f"unexpected pak table format: {root / rel}")


def _add_alias(target: dict[str, set[int]], alias: object, entity_id: int) -> None:
    text = str(alias or "").strip()
    if text:
        target[text].add(entity_id)


def _dedupe(items: list[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        text = item.strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return tuple(out)


class PakLookup:
    """Build exact lookup indexes from the extracted pak data directory."""

    def __init__(self, pak_dir: str | Path = DEFAULT_PAK_DATA_DIR):
        self.root = Path(pak_dir)
        self.data = PakData(self.root)
        self.desc_notes = _desc_notes(self.data.desc_note_conf)
        self.level_skill_conf = _table(self.root, "BinData/LEVEL_SKILL_CONF.json")
        self.bag_item_conf = _table(self.root, "BinData/BAG_ITEM_CONF.json")
        self.pet_handbook = _table(self.root, "BinData/PET_HANDBOOK.json")
        self.skill_filter_conf = _table(self.root, "BinData/SKILL_FILTER_CONF.json")
        self.handbook_rewards = self._load_optional_json("handbook-rewards.json", {})

        self.pets: dict[int, PetInfo] = {}
        self.skills: dict[int, SkillInfo] = {}
        self.abilities: dict[int, AbilityInfo] = {}
        self.pet_aliases: dict[str, set[int]] = defaultdict(set)
        self.skill_aliases: dict[str, set[int]] = defaultdict(set)
        self.ability_aliases: dict[str, set[int]] = defaultdict(set)
        self.learn_links_by_pet: dict[int, list[LearnLink]] = defaultdict(list)
        self.learn_links_by_skill: dict[int, list[LearnLink]] = defaultdict(list)
        self.ability_owners_by_ability: dict[int, list[AbilityOwner]] = defaultdict(list)
        self.skill_item_sources: dict[int, tuple[SkillItemSource, ...]] = {}

        self._build()

    def _load_optional_json(self, rel: str, default: Any) -> Any:
        path = self.root / rel
        return _load_json(path) if path.exists() else default

    def _build(self) -> None:
        move_by_id = {_int(row.get("id")): row for row in self.data.moves}
        skill_hints = self._skill_name_hints_from_level_conf()
        skill_hints.update(self._skill_name_hints_from_items())

        for raw in self.data.pets:
            pet_id = _int(raw.get("id"))
            if pet_id <= 0 or str(pet_id) not in self.data.petbase_conf:
                continue
            aliases = _dedupe([
                _pet_display_name(raw),
                str(raw.get("name", "")),
                str(pet_id),
            ])
            pet = PetInfo(pet_id, aliases[0] if aliases else str(pet_id), aliases)
            self.pets[pet_id] = pet
            for alias in aliases:
                _add_alias(self.pet_aliases, alias, pet_id)

        for skill_id, row in sorted(
            ((_int(row.get("id")), row) for row in self.data.skill_conf.values()),
            key=lambda item: item[0],
        ):
            if skill_id <= 0:
                continue
            merged = dict(row)
            if skill_id in move_by_id:
                merged["_move_record"] = move_by_id[skill_id]
            record = _skill_record(merged, self.desc_notes)
            aliases = [str(skill_id)]
            aliases.extend(skill_hints.get(skill_id, ()))
            aliases.extend([
                str(record.get("name", "")),
                str(record.get("effect_text", "")),
                str(row.get("name", "")),
                str(row.get("desc", "")),
            ])
            move = move_by_id.get(skill_id) or {}
            zh = (move.get("localized") or {}).get("zh") if isinstance(move, Mapping) else {}
            if isinstance(zh, Mapping):
                aliases.extend([str(zh.get("name", "")), str(zh.get("description", ""))])
            display = _dedupe(skill_hints.get(skill_id, ()))[:1] or (str(record.get("name", "")) or str(skill_id),)
            info = SkillInfo(
                skill_id,
                display[0],
                str(record.get("effect_text", "")),
                _dedupe(aliases),
            )
            self.skills[skill_id] = info
            for alias in info.aliases:
                _add_alias(self.skill_aliases, _clean_desc(alias, self.desc_notes), skill_id)

        feature_ids: set[int] = set()
        for pet_id, base in self.data.petbase_conf.items():
            owner_id = _int(pet_id)
            if owner_id not in self.pets:
                continue
            seen_for_pet: set[tuple[int, str]] = set()
            for field_name in ("pet_feature", "pet_chaos_feature", "pet_glass_feature"):
                ability_id = _int(base.get(field_name))
                if ability_id <= 0 or str(ability_id) not in self.data.skill_conf:
                    continue
                feature_ids.add(ability_id)
                owner_key = (ability_id, field_name)
                if owner_key not in seen_for_pet:
                    self.ability_owners_by_ability[ability_id].append(
                        AbilityOwner(owner_id, ability_id, field_name)
                    )
                    seen_for_pet.add(owner_key)

        feature_rows = [self.data.skill_conf[str(fid)] for fid in sorted(feature_ids)]
        name_counts: dict[str, int] = defaultdict(int)
        for row in feature_rows:
            name_counts[str(row.get("name", "")).strip()] += 1
        for row in feature_rows:
            ability_id = _int(row.get("id"))
            display = str(row.get("name", "")).strip() or f"feature_{ability_id}"
            name = display if name_counts[display] == 1 else f"{display}#{ability_id}"
            desc = _clean_desc(row.get("desc", ""), self.desc_notes)
            aliases = _dedupe([str(ability_id), name, display])
            info = AbilityInfo(ability_id, name, desc, aliases)
            self.abilities[ability_id] = info
            for alias in aliases:
                _add_alias(self.ability_aliases, alias, ability_id)

        self.skill_item_sources = self._build_skill_item_sources()
        self._build_learn_links()

    def _skill_name_hints_from_level_conf(self) -> dict[int, tuple[str, ...]]:
        hints: dict[int, list[str]] = defaultdict(list)
        for row in self.level_skill_conf.values():
            for entry in row.get("machine_skill_group", []) or []:
                skill_id = _int(entry.get("machine_skill_id"))
                if skill_id > 0:
                    hints[skill_id].append(str(entry.get("machine_skill_name", "")))
        return {skill_id: _dedupe(values) for skill_id, values in hints.items()}

    def _skill_name_hints_from_items(self) -> dict[int, tuple[str, ...]]:
        hints: dict[int, list[str]] = defaultdict(list)
        for item in self.bag_item_conf.values():
            for skill_id in self._learn_skill_ids_from_item(item):
                hints[skill_id].append(str(item.get("name", "")))
        return {skill_id: _dedupe(values) for skill_id, values in hints.items()}

    def _learn_skill_ids_from_item(self, item: Mapping[str, Any]) -> tuple[int, ...]:
        ids: list[int] = []
        for behavior in item.get("item_behavior", []) or []:
            if not isinstance(behavior, Mapping):
                continue
            if _int(behavior.get("use_action")) != LEARN_SKILL_ACTION:
                continue
            for raw in behavior.get("ratio", []) or []:
                skill_id = _int(raw)
                if skill_id > 0:
                    ids.append(skill_id)
        return tuple(ids)

    def _build_skill_item_sources(self) -> dict[int, tuple[SkillItemSource, ...]]:
        reward_to_items: dict[int, set[int]] = defaultdict(set)
        if isinstance(self.handbook_rewards, Mapping):
            for reward_id_raw, rewards in self.handbook_rewards.items():
                reward_id = _int(reward_id_raw)
                if not isinstance(rewards, list):
                    continue
                for reward in rewards:
                    if isinstance(reward, Mapping):
                        item_id = _int(reward.get("id"))
                        if item_id > 0:
                            reward_to_items[reward_id].add(item_id)

        handbook_by_item: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for handbook in self.pet_handbook.values():
            pet_name = str(handbook.get("name", "")).strip()
            pet_ids = tuple(
                _int(pid)
                for group in handbook.get("include_petbase_id", []) or []
                for pid in (group.get("petbase_id", []) if isinstance(group, Mapping) else [])
                if _int(pid) > 0
            )
            for topic in handbook.get("pet_topic", []) or []:
                if not isinstance(topic, Mapping):
                    continue
                reward_id = _int(topic.get("topic_reward"))
                for item_id in reward_to_items.get(reward_id, ()):
                    handbook_by_item[item_id].append({
                        "handbook_id": _int(handbook.get("id")),
                        "handbook_pet": pet_name,
                        "pet_ids": pet_ids,
                        "topic_desc": str(topic.get("topic_desc", "")),
                        "topic_type": _int(topic.get("topic_type")),
                    })

        by_skill: dict[int, list[SkillItemSource]] = defaultdict(list)
        for item in self.bag_item_conf.values():
            item_id = _int(item.get("id"))
            if item_id <= 0:
                continue
            skill_ids = self._learn_skill_ids_from_item(item)
            if not skill_ids:
                continue
            acquire = _dedupe([
                str(entry.get("acquire_way_text", ""))
                for entry in item.get("acquire_struct", []) or []
                if isinstance(entry, Mapping)
            ])
            source = SkillItemSource(
                item_id=item_id,
                item_name=str(item.get("name", "")).strip(),
                item_description=_clean_desc(item.get("description", ""), self.desc_notes),
                acquire=acquire,
                handbook=tuple(handbook_by_item.get(item_id, ())),
            )
            for skill_id in skill_ids:
                by_skill[skill_id].append(source)
        return {skill_id: tuple(rows) for skill_id, rows in by_skill.items()}

    def _bloodline_labels(self) -> dict[str, str]:
        labels: dict[str, str] = {}
        for row in self.skill_filter_conf.values():
            if _int(row.get("filter_type")) != 2:
                continue
            for value in row.get("filter_enum_value", []) or []:
                key = str(value).removeprefix("SDT_")
                if key:
                    labels[key] = str(row.get("filter_desc", "")).strip()
        return labels

    def _build_learn_links(self) -> None:
        bloodline_labels = self._bloodline_labels()
        for pet_id, pet in sorted(self.pets.items()):
            petbase = self.data.petbase_conf.get(str(pet_id), {})
            level_id = _int(petbase.get("level_skill_conf_id"), pet_id)
            conf = self.level_skill_conf.get(str(level_id))
            if not conf:
                continue

            for entry in conf.get("level", []) or []:
                if not isinstance(entry, Mapping):
                    continue
                skill_id = _int(entry.get("param"))
                if skill_id <= 0:
                    continue
                self._add_learn_link(LearnLink(
                    pet_id=pet_id,
                    skill_id=skill_id,
                    source_type="base",
                    source_label="基础技能",
                    level_point=_int(entry.get("level_point")),
                    stage=_int(entry.get("stage")),
                ))

            for entry in conf.get("machine_skill_group", []) or []:
                if not isinstance(entry, Mapping):
                    continue
                skill_id = _int(entry.get("machine_skill_id"))
                if skill_id <= 0:
                    continue
                self._add_learn_link(LearnLink(
                    pet_id=pet_id,
                    skill_id=skill_id,
                    source_type="stone",
                    source_label="技能石技能",
                    skill_name_hint=str(entry.get("machine_skill_name", "")),
                    item_sources=self.skill_item_sources.get(skill_id, ()),
                ))

            blood_level = _int(conf.get("blood_skill_level_point")) or None
            for key, raw_skill_id in conf.items():
                if not key.startswith("blood_skill_") or key == "blood_skill_level_point":
                    continue
                skill_id = _int(raw_skill_id)
                if skill_id <= 0:
                    continue
                blood_key = key.removeprefix("blood_skill_")
                self._add_learn_link(LearnLink(
                    pet_id=pet_id,
                    skill_id=skill_id,
                    source_type="bloodline",
                    source_label="血脉技能",
                    level_point=blood_level,
                    bloodline=bloodline_labels.get(blood_key, blood_key),
                ))

            legendary_skill = _int(conf.get("legendary_skill"))
            if legendary_skill > 0:
                condition_pet_id = _int(conf.get("legendary_skill_condition"))
                condition_pet = self.pets.get(condition_pet_id)
                label = "传说技能"
                if condition_pet:
                    label = f"{label}: {condition_pet.name}"
                self._add_learn_link(LearnLink(
                    pet_id=pet_id,
                    skill_id=legendary_skill,
                    source_type="legendary",
                    source_label=label,
                ))

    def _add_learn_link(self, link: LearnLink) -> None:
        self.learn_links_by_pet[link.pet_id].append(link)
        self.learn_links_by_skill[link.skill_id].append(link)

    def find_pets(self, query: str) -> list[PetInfo]:
        ids = self._find_ids(query, self.pet_aliases)
        return [self.pets[pid] for pid in sorted(ids) if pid in self.pets]

    def find_skills(self, query: str) -> list[SkillInfo]:
        ids = self._find_ids(query, self.skill_aliases)
        return [self.skills[sid] for sid in sorted(ids) if sid in self.skills]

    def find_abilities(self, query: str) -> list[AbilityInfo]:
        ids = self._find_ids(query, self.ability_aliases)
        return [self.abilities[aid] for aid in sorted(ids) if aid in self.abilities]

    def _find_ids(self, query: str, aliases: Mapping[str, set[int]]) -> set[int]:
        text = query.strip()
        if not text:
            return set()
        if text in aliases:
            return set(aliases[text])
        cleaned = _clean_desc(text, self.desc_notes)
        if cleaned in aliases:
            return set(aliases[cleaned])
        return set()

    def pet_report(self, query: str) -> list[dict[str, Any]]:
        reports: list[dict[str, Any]] = []
        for pet in self.find_pets(query):
            base = self.data.petbase_conf.get(str(pet.id), {})
            ability_ids = _dedupe([
                str(_int(base.get(field)))
                for field in ("pet_feature", "pet_chaos_feature", "pet_glass_feature")
                if _int(base.get(field)) > 0
            ])
            abilities = [self.abilities[_int(aid)] for aid in ability_ids if _int(aid) in self.abilities]
            links = self.learn_links_by_pet.get(pet.id, [])
            reports.append({
                "pet": pet,
                "abilities": abilities,
                "base_skills": [link for link in links if link.source_type == "base"],
                "bloodline_skills": [link for link in links if link.source_type == "bloodline"],
                "stone_skills": [link for link in links if link.source_type == "stone"],
                "legendary_skills": [link for link in links if link.source_type == "legendary"],
            })
        return reports

    def skill_report(self, query: str) -> list[dict[str, Any]]:
        reports: list[dict[str, Any]] = []
        for skill in self.find_skills(query):
            reports.append({
                "skill": skill,
                "item_sources": self.skill_item_sources.get(skill.id, ()),
                "learners": self.learn_links_by_skill.get(skill.id, []),
            })
        return reports

    def ability_report(self, query: str) -> list[dict[str, Any]]:
        reports: list[dict[str, Any]] = []
        for ability in self.find_abilities(query):
            reports.append({
                "ability": ability,
                "owners": self.ability_owners_by_ability.get(ability.id, []),
            })
        return reports
