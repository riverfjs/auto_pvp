"""Import structured JSON into the normalized SQLite data store."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable

from roco.data.utils import PARSED_DIR, DB_DIR, load_json
from roco.engine.skill_tags import classify
from roco.engine.state import (
    EffectFlag,
    EffectTag,
    Element,
    SkillCategory,
    SkillData,
    Timing,
    normalize_element_name,
)


def _safe_int(val: object) -> int | None:
    try:
        if val is None or val == "":
            return None
        return int(val)
    except (ValueError, TypeError):
        return None


def _required_int(val: object, default: int = 0) -> int:
    parsed = _safe_int(val)
    return default if parsed is None else parsed


def _element_id(conn: sqlite3.Connection, raw: str) -> int:
    name = normalize_element_name(raw)
    row = conn.execute("SELECT id FROM elements WHERE name = ?", (name,)).fetchone()
    if row is None:
        raise ValueError(f"element not seeded: {name}")
    return int(row[0])


def _maybe_element_id(conn: sqlite3.Connection, raw: str | None) -> int | None:
    if not raw:
        return None
    return _element_id(conn, raw)


def _category(raw: object) -> tuple[int, str]:
    if isinstance(raw, SkillCategory):
        return raw.value, _CATEGORY_NAMES[raw]
    text = str(raw or "").strip()
    cat = _CATEGORY_MAP.get(text)
    if not cat:
        raise ValueError(f"unknown skill category: {raw!r}")
    return cat.value, _CATEGORY_NAMES[cat]


_CATEGORY_MAP = {
    "物攻": SkillCategory.PHYSICAL,
    "魔攻": SkillCategory.MAGICAL,
    "防御": SkillCategory.DEFENSE,
    "状态": SkillCategory.STATUS,
}

_CATEGORY_NAMES = {
    SkillCategory.PHYSICAL: "物攻",
    SkillCategory.MAGICAL: "魔攻",
    SkillCategory.DEFENSE: "防御",
    SkillCategory.STATUS: "状态",
}


def _skill_from_raw(name: str, sk: dict) -> SkillData:
    category_code, _category_name = _category(sk.get("技能类别", "物攻"))
    skill = SkillData(
        name=sk.get("技能名称", name),
        element=normalize_element_name(sk.get("属性", "普通")),
        category=SkillCategory(category_code),
        energy=_required_int(sk.get("耗能"), 0),
        power=_required_int(sk.get("威力"), 0),
        effect=sk.get("效果", ""),
    )
    return classify(skill)


def _json(data: object) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def _effect_rows_for_skill(skill_id: int, skill: SkillData) -> list[tuple]:
    rows: list[tuple] = []

    def add(timing: Timing, tag: EffectTag, params: dict, sort_order: int) -> None:
        rows.append((skill_id, timing.value, tag.value, int(skill.effect_flags), _json(params), "", sort_order))

    order = 0
    if skill.power > 0 or skill.effect_flags & EffectFlag.PURE_DAMAGE:
        add(Timing.ON_DAMAGE, EffectTag.DAMAGE, {"power": skill.power, "hit_count": skill.hit_count}, order); order += 1
    if skill.life_drain:
        add(Timing.ON_DAMAGE, EffectTag.LIFE_DRAIN, {"pct": skill.life_drain}, order); order += 1
    if skill.self_heal_hp:
        add(Timing.AFTER_MOVE, EffectTag.HEAL_HP, {"pct": skill.self_heal_hp}, order); order += 1
    if skill.self_heal_energy:
        add(Timing.AFTER_MOVE, EffectTag.HEAL_ENERGY, {"amount": skill.self_heal_energy}, order); order += 1
    if skill.steal_energy:
        add(Timing.AFTER_MOVE, EffectTag.STEAL_ENERGY, {"amount": skill.steal_energy}, order); order += 1
    if skill.enemy_lose_energy:
        add(Timing.AFTER_MOVE, EffectTag.ENEMY_LOSE_ENERGY, {"amount": skill.enemy_lose_energy}, order); order += 1
    if skill.damage_reduction:
        add(Timing.BEFORE_MOVE, EffectTag.DAMAGE_REDUCTION, {"pct": skill.damage_reduction}, order); order += 1
    for tag, stacks in (
        (EffectTag.BURN, skill.burn_stacks),
        (EffectTag.POISON, skill.poison_stacks),
        (EffectTag.FREEZE, skill.freeze_stacks),
        (EffectTag.LEECH, skill.leech_stacks),
        (EffectTag.METEOR, skill.meteor_stacks),
    ):
        if stacks:
            add(Timing.AFTER_MOVE, tag, {"stacks": stacks}, order); order += 1
    if skill.force_switch:
        add(Timing.AFTER_MOVE, EffectTag.FORCE_SWITCH, {}, order); order += 1
    if skill.effect_flags & EffectFlag.ENERGY_ALL_IN:
        add(Timing.BEFORE_MOVE, EffectTag.ENERGY_ALL_IN, {}, order); order += 1
    if skill.weather_type:
        add(Timing.AFTER_MOVE, EffectTag.WEATHER, {"type": skill.weather_type, "turns": 5}, order); order += 1
    return rows


def _ability_effect_rows(ability_id: int, name: str) -> Iterable[tuple]:
    if name == "诈死":
        yield (ability_id, Timing.FAINT.value, EffectTag.FAINT_NO_MP_LOSS.value, 0, "{}", "", 0)
    elif name == "蓄能":
        yield (ability_id, Timing.TURN_END.value, EffectTag.ENERGY_REGEN_PER_TURN.value, 0, '{"amount":1}', "", 0)


def import_abilities(conn: sqlite3.Connection, pets: dict[str, dict]) -> dict[str, int]:
    rows: dict[str, str] = {}
    for pet in pets.values():
        name = pet.get("特性", "").strip()
        if name:
            rows.setdefault(name, pet.get("特性描述", ""))
    conn.executemany(
        "INSERT INTO abilities (name, description) VALUES (?, ?)",
        sorted(rows.items()),
    )
    lookup = {name: aid for aid, name in conn.execute("SELECT id, name FROM abilities")}
    effect_rows = []
    for name, aid in lookup.items():
        effect_rows.extend(_ability_effect_rows(aid, name))
    if effect_rows:
        conn.executemany(
            "INSERT INTO ability_effects (ability_id, timing_code, tag_code, flags, params_json, condition, sort_order) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            effect_rows,
        )
    print(f"  abilities: {len(lookup)} inserted")
    return lookup


def import_skills(conn: sqlite3.Connection, skills: dict[str, dict]) -> dict[str, int]:
    lookup: dict[str, int] = {}
    rows: list[tuple] = []
    compiled: list[SkillData] = []
    for name, raw in skills.items():
        skill = _skill_from_raw(name, raw)
        category_code, category_name = _category(skill.category)
        rows.append((
            skill.name,
            _element_id(conn, skill.element),
            category_code,
            category_name,
            skill.energy,
            skill.power,
            skill.effect,
            raw.get("描述", ""),
            int(skill.effect_flags),
            raw.get("技能版本", ""),
        ))
        compiled.append(skill)
    conn.executemany(
        "INSERT INTO skills (name, element_id, category_code, category_name, energy, power, effect_text, flavor_text, flags, source_version) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    lookup = {name: sid for sid, name in conn.execute("SELECT id, name FROM skills")}
    effect_rows: list[tuple] = []
    for skill in compiled:
        skill_id = lookup[skill.name]
        effect_rows.extend(_effect_rows_for_skill(skill_id, skill))
    if effect_rows:
        conn.executemany(
            "INSERT INTO skill_effects (skill_id, timing_code, tag_code, flags, params_json, condition, sort_order) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            effect_rows,
        )
    print(f"  skills: {len(lookup)} inserted")
    print(f"  skill_effects: {len(effect_rows)} inserted")
    return lookup


def import_pets(
    conn: sqlite3.Connection,
    pets: dict[str, dict],
    skill_lookup: dict[str, int],
    ability_lookup: dict[str, int],
) -> dict[str, int]:
    rows: list[tuple] = []
    for name, pet in pets.items():
        ability_name = pet.get("特性", "").strip()
        rows.append((
            name,
            pet.get("地区形态名称", ""),
            pet.get("精灵阶段", ""),
            pet.get("精灵形态", ""),
            _element_id(conn, pet.get("主属性", "普通")),
            _maybe_element_id(conn, pet.get("2属性")),
            ability_lookup.get(ability_name),
            _required_int(pet.get("生命"), 1),
            _required_int(pet.get("物攻"), 0),
            _required_int(pet.get("魔攻"), 0),
            _required_int(pet.get("物防"), 0),
            _required_int(pet.get("魔防"), 0),
            _required_int(pet.get("速度"), 0),
            pet.get("体型", ""),
            pet.get("重量", ""),
            pet.get("分布地区", ""),
            pet.get("精灵描述", ""),
            1 if pet.get("是否有异色") == "是" else 0,
            pet.get("进化条件", ""),
            pet.get("更新版本", ""),
        ))
    conn.executemany(
        "INSERT INTO pets (name, form_name, stage, form_type, element_primary_id, element_secondary_id, ability_id, "
        "hp, atk_phys, atk_mag, def_phys, def_mag, speed, height, weight, distribution, description, is_shiny, evolution_cond, source_version) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    pet_lookup = {name: pid for pid, name in conn.execute("SELECT id, name FROM pets")}

    link_rows: list[tuple] = []
    for field, source_type in (("技能", "技能"), ("血脉技能", "血脉技能"), ("可学技能石", "可学技能石")):
        for name, pet in pets.items():
            levels: list[str] = pet.get("技能解锁等级", []) if field == "技能" else []
            for i, skill_name in enumerate(pet.get(field, [])):
                link_rows.append((
                    pet_lookup[name],
                    skill_lookup.get(skill_name),
                    skill_name,
                    source_type,
                    _safe_int(levels[i]) if i < len(levels) else None,
                    i,
                ))
    conn.executemany(
        "INSERT INTO pet_skills (pet_id, skill_id, skill_name, source_type, unlock_level, sort_order) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        link_rows,
    )
    print(f"  pets: {len(pet_lookup)} inserted")
    print(f"  pet_skills: {len(link_rows)} links inserted")
    return pet_lookup


def import_yinji(conn: sqlite3.Connection, yinji: dict[str, dict]) -> None:
    skill_lookup = {name: sid for sid, name in conn.execute("SELECT id, name FROM skills")}
    rows: list[tuple] = []
    for mark_name, mark in yinji.items():
        for skill_name, desc in mark.get("可施加技能", {}).items():
            sid = skill_lookup.get(skill_name)
            if sid:
                rows.append((
                    sid,
                    Timing.AFTER_MOVE.value,
                    EffectTag.MARK.value,
                    0,
                    _json({"mark": mark_name, "description": desc}),
                    "",
                    100,
                ))
    if rows:
        conn.executemany(
            "INSERT INTO skill_effects (skill_id, timing_code, tag_code, flags, params_json, condition, sort_order) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
    print(f"  yinji skill_effects: {len(rows)} inserted")


def import_teams(conn: sqlite3.Connection, teams: dict[str, dict], pet_lookup: dict[str, int], skill_lookup: dict[str, int]) -> None:
    team_rows: list[tuple] = []
    pet_rows: list[tuple] = []
    skill_rows: list[tuple] = []

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
    conn.executemany(
        "INSERT INTO teams (id, title, author, team_type, bloodline_magic, description, upload_date) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        team_rows,
    )

    for tid, team in teams.items():
        for pet in team.get("pets", []):
            pet_rows.append((
                tid,
                int(pet.get("slot", 0)),
                pet_lookup.get(pet.get("name", "")) or pet_lookup.get(pet.get("name_short", "")),
                pet.get("name", ""),
                pet.get("name_short", ""),
                pet.get("bloodline", ""),
                pet.get("nature", ""),
                _json(pet.get("ivs", [])),
            ))
    conn.executemany(
        "INSERT INTO team_pets (team_id, slot, pet_id, pet_name, name_short, bloodline, nature, ivs_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        pet_rows,
    )

    team_pet_ids = {
        (team_id, slot): tpid
        for tpid, team_id, slot in conn.execute("SELECT id, team_id, slot FROM team_pets")
    }
    for tid, team in teams.items():
        for pet in team.get("pets", []):
            tpid = team_pet_ids[(tid, int(pet.get("slot", 0)))]
            for i, move in enumerate(pet.get("moves", []), start=1):
                skill_rows.append((tpid, i, skill_lookup.get(move), move))
    conn.executemany(
        "INSERT INTO team_pet_skills (team_pet_id, slot, skill_id, skill_name) VALUES (?, ?, ?, ?)",
        skill_rows,
    )
    print(f"  teams: {len(team_rows)} inserted")
    print(f"  team_pets: {len(pet_rows)} slots inserted")
    print(f"  team_pet_skills: {len(skill_rows)} moves inserted")


def main() -> None:
    db_path = DB_DIR / "data.db"
    if not db_path.exists():
        print(f"Database not found: {db_path}")
        print("Run 'python -m roco.data.migrate' first.")
        return

    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")

    print("Importing...")
    skills: dict[str, dict] = load_json(PARSED_DIR / "skills.json")
    pets: dict[str, dict] = load_json(PARSED_DIR / "pets.json")

    ability_lookup = import_abilities(conn, pets)
    skill_lookup = import_skills(conn, skills)
    pet_lookup = import_pets(conn, pets, skill_lookup, ability_lookup)

    yinji_path = PARSED_DIR / "yinji.json"
    if yinji_path.exists():
        import_yinji(conn, load_json(yinji_path))

    teams_path = PARSED_DIR / "teams.json"
    if teams_path.exists():
        import_teams(conn, load_json(teams_path), pet_lookup, skill_lookup)

    conn.commit()
    for name, in conn.execute(
        "SELECT 'pets' UNION ALL SELECT 'skills' UNION ALL SELECT 'abilities' UNION ALL "
        "SELECT 'pet_skills' UNION ALL SELECT 'skill_effects' UNION ALL SELECT 'teams' UNION ALL "
        "SELECT 'team_pets' UNION ALL SELECT 'team_pet_skills'"
    ):
        cnt = conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
        print(f"  {name}: {cnt}")
    conn.close()
    print(f"Done -> {db_path}")


if __name__ == "__main__":
    main()
