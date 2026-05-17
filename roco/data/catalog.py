"""Compile SQLite data into runtime-friendly Pet and skill catalogs."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

from roco.data.utils import DB_DIR
from roco.engine.state import (
    AbilityEffect,
    EffectSpec,
    EffectTag,
    PetData,
    PersistentPet,
    SkillCategory,
    SkillData,
    SkillEffect,
    Stats,
    Timing,
)


@dataclass(frozen=True, slots=True)
class RuntimeCatalog:
    elements_by_id: dict[int, str]
    elements_by_name: dict[str, int]
    skills_by_id: dict[int, SkillData]
    skills_by_name: dict[str, SkillData]
    pets_by_id: dict[int, PetData]
    pets_by_name: dict[str, PetData]
    pet_skill_ids: dict[int, tuple[int, ...]]
    ability_effects: dict[int, tuple[AbilityEffect, ...]]
    unsupported_effect_stats: tuple[tuple[str, int], ...] = ()

    def build_pet(self, name: str, skill_names: list[str] | None = None) -> PersistentPet:
        data = self.pets_by_name[name]
        if skill_names:
            moves = tuple(self.skills_by_name[s] for s in skill_names if s in self.skills_by_name)
        else:
            moves = tuple(self.skills_by_id[sid] for sid in self.pet_skill_ids.get(data.pet_id, ())[:4])
        return PersistentPet.from_data(data, moves, ability_effects=self.ability_effects.get(data.ability_id, ()))


def _connect(path_or_conn: str | Path | sqlite3.Connection | None) -> tuple[sqlite3.Connection, bool]:
    if isinstance(path_or_conn, sqlite3.Connection):
        return path_or_conn, False
    path = Path(path_or_conn) if path_or_conn else DB_DIR / "data.db"
    conn = sqlite3.connect(str(path))
    return conn, True


def _params(raw: str) -> MappingProxyType[str, Any]:
    return MappingProxyType(json.loads(raw or "{}"))


def _load_skill_effects(conn: sqlite3.Connection) -> dict[int, tuple[SkillEffect, ...]]:
    rows = conn.execute(
        "SELECT skill_id, timing_code, tag_code, params_json, condition, sort_order "
        "FROM skill_effects ORDER BY skill_id, sort_order, id"
    )
    by_skill: dict[int, list[SkillEffect]] = {}
    for skill_id, timing, tag, params, condition, sort_order in rows:
        spec = EffectSpec(EffectTag(tag), Timing(timing), _params(params), 1.0, condition or "")
        by_skill.setdefault(skill_id, []).append(SkillEffect(skill_id, spec, sort_order))
    return {sid: tuple(items) for sid, items in by_skill.items()}


def _load_ability_effects(conn: sqlite3.Connection) -> dict[int, tuple[AbilityEffect, ...]]:
    rows = conn.execute(
        "SELECT ability_id, timing_code, tag_code, params_json, condition, sort_order "
        "FROM ability_effects ORDER BY ability_id, sort_order, id"
    )
    by_ability: dict[int, list[AbilityEffect]] = {}
    for ability_id, timing, tag, params, condition, sort_order in rows:
        spec = EffectSpec(EffectTag(tag), Timing(timing), _params(params), 1.0, condition or "")
        by_ability.setdefault(ability_id, []).append(AbilityEffect(ability_id, spec, sort_order))
    return {aid: tuple(items) for aid, items in by_ability.items()}


def compile_catalog(path_or_conn: str | Path | sqlite3.Connection | None = None) -> RuntimeCatalog:
    conn, should_close = _connect(path_or_conn)
    try:
        conn.row_factory = sqlite3.Row
        elements_by_id = {row["id"]: row["name"] for row in conn.execute("SELECT id, name FROM elements")}
        elements_by_name = {name: eid for eid, name in elements_by_id.items()}
        skill_effects = _load_skill_effects(conn)

        skills_by_id: dict[int, SkillData] = {}
        for row in conn.execute(
            "SELECT s.*, e.name AS element_name FROM skills s JOIN elements e ON e.id = s.element_id"
        ):
            effects = skill_effects.get(row["id"], ())
            skill = SkillData(
                name=row["name"],
                element=row["element_name"],
                category=SkillCategory(row["category_code"]),
                energy=row["energy"],
                power=row["power"],
                effect=row["effect_text"] or "",
                skill_id=row["id"],
                element_id=row["element_id"],
                effect_flags=row["flags"],
                effects=effects,
                hit_count=_damage_hit_count(effects),
            )
            skills_by_id[row["id"]] = skill
        skills_by_name = {skill.name: skill for skill in skills_by_id.values()}

        pets_by_id: dict[int, PetData] = {}
        for row in conn.execute(
            """
            SELECT p.*, ep.name AS primary_name, es.name AS secondary_name,
                   a.name AS ability_name, a.description AS ability_desc
            FROM pets p
            JOIN elements ep ON ep.id = p.element_primary_id
            LEFT JOIN elements es ON es.id = p.element_secondary_id
            LEFT JOIN abilities a ON a.id = p.ability_id
            """
        ):
            stats = (
                row["hp"], row["atk_phys"], row["atk_mag"],
                row["def_phys"], row["def_mag"], row["speed"],
            )
            pets_by_id[row["id"]] = PetData(
                pet_id=row["id"],
                name=row["name"],
                stats=stats,
                types=(row["primary_name"], row["secondary_name"] or ""),
                ability_id=row["ability_id"] or 0,
                ability_name=row["ability_name"] or "",
                ability_desc=row["ability_desc"] or "",
            )
        pets_by_name = {pet.name: pet for pet in pets_by_id.values()}

        pet_skill_ids: dict[int, tuple[int, ...]] = {}
        for row in conn.execute(
            "SELECT pet_id, skill_id FROM pet_skills WHERE skill_id IS NOT NULL ORDER BY pet_id, sort_order, id"
        ):
            pet_skill_ids.setdefault(row["pet_id"], ())
            pet_skill_ids[row["pet_id"]] = pet_skill_ids[row["pet_id"]] + (row["skill_id"],)
        for pet_id, skill_ids in pet_skill_ids.items():
            if pet_id in pets_by_id:
                pets_by_id[pet_id].skill_ids = skill_ids

        ability_effects = _load_ability_effects(conn)
        unsupported: dict[str, int] = {}
        for items in tuple(skill_effects.values()) + tuple(ability_effects.values()):
            for item in items:
                if item.effect.tag is EffectTag.UNSUPPORTED:
                    kind = str(item.effect.params.get("primitive", item.effect.params.get("tag", "UNSUPPORTED")))
                    unsupported[kind] = unsupported.get(kind, 0) + 1
        try:
            gap_rows = conn.execute("SELECT primitive FROM effect_gaps")
        except sqlite3.OperationalError:
            gap_rows = ()
        for row in gap_rows:
            primitive = row["primitive"] if isinstance(row, sqlite3.Row) else row[0]
            unsupported[str(primitive)] = unsupported.get(str(primitive), 0) + 1
        try:
            no_effect_rows = conn.execute(
                """
                SELECT a.name
                FROM abilities a
                LEFT JOIN ability_effects ae ON ae.ability_id = a.id
                WHERE NOT EXISTS (
                    SELECT 1 FROM effect_gaps eg
                    WHERE eg.source_type = 'ability' AND eg.source_name = a.name
                )
                GROUP BY a.id
                HAVING COUNT(ae.id) = 0
                """
            )
        except sqlite3.OperationalError:
            no_effect_rows = conn.execute(
                """
                SELECT a.name
                FROM abilities a
                LEFT JOIN ability_effects ae ON ae.ability_id = a.id
                GROUP BY a.id
                HAVING COUNT(ae.id) = 0
                """
            )
        for row in no_effect_rows:
            unsupported[row["name"]] = unsupported.get(row["name"], 0) + 1
        return RuntimeCatalog(
            elements_by_id=elements_by_id,
            elements_by_name=elements_by_name,
            skills_by_id=skills_by_id,
            skills_by_name=skills_by_name,
            pets_by_id=pets_by_id,
            pets_by_name=pets_by_name,
            pet_skill_ids=pet_skill_ids,
            ability_effects=ability_effects,
            unsupported_effect_stats=tuple(sorted(unsupported.items())),
        )
    finally:
        if should_close:
            conn.close()


load_catalog = compile_catalog


def _damage_hit_count(effects: tuple[SkillEffect, ...]) -> int:
    for item in effects:
        if item.effect.tag is EffectTag.DAMAGE:
            return max(1, int(item.effect.params.get("hit_count", 1)))
    return 1
