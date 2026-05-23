"""Build canonical records from extracted New Roco pak data.

Default source:
  <project_root>/pak-public-kit/output/data

The pak dump is the authoritative source for pets, skills, abilities, marks,
bloodlines, and battle-facing static fields. BWiki remains a team sample source
only and is not consulted here.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
from collections import Counter
from pathlib import Path
from typing import Any

from roco.compiler_v2.effect_codegen import PakTables, build_ability_effect_rows, generate_effect_rows
from roco.generated.canonical_adapters import CANONICAL_MARK_DEFS, MOVE_CATEGORY_TO_CN
from roco.data.utils import content_hash, with_canonical_hash, write_jsonl
from roco.generated.skill_dam_types import SKILL_DAM_TYPE_TO_ELEMENT_NAME


DEFAULT_PAK_DATA_DIR = Path(
    os.environ.get(
        "ROCO_PAK_DATA_DIR",
        str(Path(__file__).resolve().parents[2] / "pak-public-kit" / "output" / "data"),
    )
)

DESC_ID_RE = re.compile(r"<desc_id=(\d+)>(.*?)</>")
TAG_RE = re.compile(r"<[^>]+>")


class PakData:
    def __init__(self, root: Path):
        self.root = root
        self.skill_conf = self.table("BinData/SKILL_CONF.json")
        self.petbase_conf = self.table("BinData/PETBASE_CONF.json")
        self.desc_note_conf = self.table("BinData/DESC_NOTE_CONF.json")
        self.pet_skill_index = self.load_json("PetSkillIndex.json")
        self.pets = self.load_json("Pets.json")
        self.moves = self.load_json("moves.json")

    def load_json(self, rel: str) -> Any:
        path = self.root / rel
        if not path.exists():
            raise FileNotFoundError(f"missing pak data file: {path}")
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)

    def table(self, rel: str) -> dict[str, dict[str, Any]]:
        data = self.load_json(rel)
        if isinstance(data, dict) and set(data) == {"RocoDataRows"}:
            rows = data["RocoDataRows"]
            if isinstance(rows, dict):
                return rows
        raise ValueError(f"unexpected table format: {self.root / rel}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pak-dir", type=Path, default=DEFAULT_PAK_DATA_DIR)
    parser.add_argument("--out-dir", type=Path, required=True, help="Debug JSONL export directory.")
    args = parser.parse_args()

    data = PakData(args.pak_dir)
    pak_tables = PakTables(data.root)
    desc_notes = _desc_notes(data.desc_note_conf)
    skills, skill_names_by_id = build_skills(data, desc_notes, pak_tables)
    abilities, ability_name_by_feature_id = build_abilities(data, desc_notes, pak_tables)
    pets = build_pets(data, ability_name_by_feature_id, skill_names_by_id)
    marks = build_marks(data, desc_notes)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    print(f"Generated {write_jsonl(skills, args.out_dir / 'skills.jsonl')} skills")
    print(f"Generated {write_jsonl(abilities, args.out_dir / 'abilities.jsonl')} abilities")
    print(f"Generated {write_jsonl(pets, args.out_dir / 'pets.jsonl')} pets")
    print(f"Generated {write_jsonl(marks, args.out_dir / 'marks.jsonl')} marks")


def build_skills(data: PakData, desc_notes: dict[int, str], pak_tables: PakTables) -> tuple[list[dict], dict[int, str]]:
    selected: dict[int, dict[str, Any]] = {}
    counter_skill_ids = _counter_response_skill_ids(pak_tables)

    for move in data.moves:
        sid = _int(move.get("id"))
        row = data.skill_conf.get(str(sid), {})
        merged = dict(row)
        merged["_move_record"] = move
        selected[sid] = merged

    selected_names = {_clean_name(row.get("name")) for row in selected.values()}
    for row in data.skill_conf.values():
        name = _clean_name(row.get("name"))
        if not name or name in selected_names:
            continue
        if row.get("Skill_Type") is None:
            continue
        if _is_internal_test_skill(row):
            continue
        selected[_int(row.get("id"))] = row
        selected_names.add(name)

    # Counter-response skills (70xxxxx) referenced as ``effect_param[0]`` of
    # pak 1031xxx counter-trigger effects.  These never appear in moves.json
    # but the kernel needs them in the canonical skills set so they show up
    # in ``hot.SKILLS`` and ``COUNTER_SKILL_TABLE`` can resolve their stats.
    for csid in counter_skill_ids:
        if csid in selected:
            continue
        row = data.skill_conf.get(str(csid))
        if row is None:
            continue
        selected[csid] = row

    records: list[dict] = []
    id_to_name: dict[int, str] = {}
    emitted_names: set[str] = set()
    for sid in sorted(selected):
        row = selected[sid]
        name = _clean_name(row.get("name"))
        if not name or name in emitted_names:
            continue
        record = _skill_record(row, desc_notes)
        skill_row = data.skill_conf.get(str(sid), row)
        effect_rows, effect_gaps = generate_effect_rows(skill_row, pak_tables)
        record["effect_rows"] = effect_rows
        record["effect_gaps"] = effect_gaps
        kind = "counter_skill" if sid in counter_skill_ids else "skill"
        source = _source(kind, sid, row)
        record = with_canonical_hash(record, source)
        records.append(record)
        emitted_names.add(name)
        id_to_name[sid] = name
    return records, id_to_name


def _counter_response_skill_ids(pak_tables: PakTables) -> set[int]:
    """Collect every 70xxxxx skill referenced by a counter-trigger effect.

    The pak counter-trigger family stores the 70xxxxx response skill_id
    in ``effect_param[0]``; pak's own axis for the family is
    ``EFFECT_CONF.effect_order == 31`` (matches
    ``Enum.EffectType.ET_COUNTER``, see
    ``SkillPerformAutoBattleUtils.lua:189``).  The kernel consumes those
    skills by id and needs them in ``hot.SKILLS``, so they must end up
    in ``skills.jsonl`` even though moves.json never references them.
    Returns an empty set when ``EFFECT_CONF`` is absent (test fixtures
    only ship the tables they exercise).
    """
    try:
        effect_conf = pak_tables.effect_conf
    except FileNotFoundError:
        return set()
    out: set[int] = set()
    for rec in effect_conf.values():
        if int(rec.get("effect_order", 0)) != 31:
            continue
        params = rec.get("effect_param") or rec.get("params") or []
        if not params or not isinstance(params[0], dict):
            continue
        inner = params[0].get("params")
        if not inner:
            continue
        csid = _int(inner[0])
        if 7000000 <= csid < 8000000:
            out.add(csid)
    return out


def build_abilities(data: PakData, desc_notes: dict[int, str], pak_tables: PakTables) -> tuple[list[dict], dict[int, str]]:
    feature_ids = sorted({
        _int(row.get(field))
        for row in data.petbase_conf.values()
        for field in ("pet_feature", "pet_chaos_feature", "pet_glass_feature")
        if _int(row.get(field)) > 0
    })
    rows = [data.skill_conf[str(fid)] for fid in feature_ids if str(fid) in data.skill_conf]
    name_counts = Counter(_clean_name(row.get("name")) for row in rows)
    records: list[dict] = []
    name_by_id: dict[int, str] = {}
    for row in rows:
        fid = _int(row.get("id"))
        display = _clean_name(row.get("name")) or f"feature_{fid}"
        name = display if name_counts[display] == 1 else f"{display}#{fid}"
        desc = _clean_desc(row.get("desc", ""), desc_notes)
        if not desc:
            raise ValueError(f"pak ability {name} has empty description")
        record = {
            "kind": "ability",
            "name": name,
            "display_name": display,
            "source_id": fid,
            "description": desc,
            "source_version": str(row.get("monitor_data_version", "")),
            "source_fields": row,
        }
        effect_rows, effect_gaps = build_ability_effect_rows(row, pak_tables)
        record["effect_rows"] = effect_rows
        record["effect_gaps"] = effect_gaps
        records.append(with_canonical_hash(record, _source("ability", fid, row)))
        name_by_id[fid] = name
    return records, name_by_id


def build_pets(
    data: PakData,
    ability_name_by_feature_id: dict[int, str],
    skill_names_by_id: dict[int, str],
) -> list[dict]:
    display_counts = Counter(_pet_display_name(row) for row in data.pets)
    first_display_seen: set[str] = set()
    rows: list[dict] = []
    for pet in sorted(data.pets, key=lambda row: _int(row.get("id"))):
        pid = _int(pet.get("id"))
        base = data.petbase_conf.get(str(pid), {})
        if not base:
            continue
        display = _pet_display_name(pet)
        name = display
        if display_counts[display] > 1:
            if display in first_display_seen:
                name = f"{display}#{pid}"
            else:
                first_display_seen.add(display)
        feature_id = _int(base.get("pet_feature"))
        ability_name = ability_name_by_feature_id.get(feature_id, "")
        ability_desc = ""
        if ability_name:
            feature = data.skill_conf.get(str(feature_id), {})
            ability_desc = _clean_desc(feature.get("desc", ""), {})
        record = {
            "kind": "pet",
            "name": name,
            "display_name": display,
            "source_id": pid,
            "form_name": _form_name(pet),
            "stage": str(base.get("stage", "")),
            "form_type": "首领形态" if pet.get("is_leader_form") else "",
            "lineage_key": _lineage_key(pid, data.pets),
            "elements": _pet_elements(pet),
            "ability": ability_name,
            "ability_description": ability_desc,
            "stats": {
                "hp": _int(base.get("hp_max_race"), _int(pet.get("base_hp"), 1)),
                "atk_phys": _int(base.get("phy_attack_race"), _int(pet.get("base_phy_atk"))),
                "atk_mag": _int(base.get("spe_attack_race"), _int(pet.get("base_mag_atk"))),
                "def_phys": _int(base.get("phy_defence_race"), _int(pet.get("base_phy_def"))),
                "def_mag": _int(base.get("spe_defence_race"), _int(pet.get("base_mag_def"))),
                "speed": _int(base.get("speed_race"), _int(pet.get("base_spd"))),
            },
            "height": _range_text(base.get("height_low"), base.get("height_high")),
            "weight": _range_text(base.get("weight_low"), base.get("weight_high")),
            "distribution": "",
            "description": _clean_desc(base.get("description", ""), {}),
            "is_shiny": bool(base.get("have_shiny") or pet.get("form") == "shiny"),
            "evolution_cond": "",
            "source_version": "",
            "skills": _pet_skill_links(pid, data.pet_skill_index, skill_names_by_id),
            "source_fields": {"pet": pet, "petbase": base},
        }
        rows.append(with_canonical_hash(record, _source("pet", pid, {"pet": pet, "petbase": base})))
    return rows


def build_marks(data: PakData, desc_notes: dict[int, str]) -> list[dict]:
    rows: list[dict] = []
    for desc_id, code, packed_index, polarity in CANONICAL_MARK_DEFS:
        raw = data.desc_note_conf.get(str(desc_id), {})
        name = str(raw.get("note", "")).strip()
        effect_text = _clean_desc(raw.get("desc", desc_notes.get(desc_id, "")), desc_notes)
        record = {
            "kind": "mark",
            "code": code,
            "name": name,
            "polarity": polarity,
            "packed_index": packed_index,
            "stacking": "stack_same_mark_replace_same_polarity",
            "effect_text": effect_text,
            "effects": [],
            "mechanism": [effect_text] if effect_text else [],
            "source_skills": [],
            "source_id": desc_id,
        }
        rows.append(with_canonical_hash(record, _source("mark", desc_id, raw)))
    return rows


SKILL_FLAG_DEVOTION = 0x01000000  # 16777216 — marks a devotion-linked skill


def _skill_flags(row: dict[str, Any]) -> int:
    """Derive skill flags from pak data fields."""
    flags = 0
    # Older pak rows used use_type='连击技'.  Current rows keep the same
    # mechanic in structured description text via desc_id=1009.
    use_type = row.get("use_type") or []
    if isinstance(use_type, list) and "连击技" in use_type:
        flags |= SKILL_FLAG_DEVOTION
    text = "\n".join(
        str(row.get(field) or "")
        for field in ("name", "desc", "flavor_text")
    )
    if "本技能会受<desc_id=1009>奉献</>影响" in text:
        flags |= SKILL_FLAG_DEVOTION
    return flags


def _skill_record(row: dict[str, Any], desc_notes: dict[int, str]) -> dict:
    move = row.get("_move_record") or {}
    name = _clean_name(row.get("name") or move.get("name"))
    element = _skill_element(row, move)
    category = _skill_category(row, move)
    power = _first_int(row.get("dam_para"), move.get("power") or 0)
    energy = _first_int(row.get("energy_cost"), move.get("energy_cost") or 0)
    desc = _clean_desc(row.get("desc") or move.get("description") or "", desc_notes)
    return {
        "kind": "skill",
        "name": name,
        "source_id": _int(row.get("id") or move.get("id")),
        "element": element,
        "category": category,
        "skill_dam_type": _int(row.get("skill_dam_type")),
        "energy": energy,
        "power": power,
        "effect_text": desc,
        "flavor_text": _clean_desc(row.get("flavor_text", ""), desc_notes),
        "source_version": str(row.get("monitor_data_version", "")),
        "source_fields": {k: v for k, v in row.items() if k != "_move_record"},
        "flags": _skill_flags(row),
    }


def _skill_element(row: dict[str, Any], move: dict[str, Any]) -> str:
    if move:
        zh = (((move.get("move_type") or {}).get("localized") or {}).get("zh") or "").strip()
        if zh and zh != "首领":
            return zh
    return SKILL_DAM_TYPE_TO_ELEMENT_NAME.get(_int(row.get("skill_dam_type")), "普通")


def _skill_category(row: dict[str, Any], move: dict[str, Any]) -> str:
    if move:
        category = MOVE_CATEGORY_TO_CN.get(str(move.get("move_category", "")))
        if category:
            return category
    stype = _int(row.get("Skill_Type"))
    dtype = _int(row.get("damage_type"))
    if stype == 3:
        return "防御"
    if stype == 2:
        return "状态"
    if dtype == 2:
        return "物攻"
    if dtype in {3, 4}:
        return "魔攻"
    return "状态"


def _pet_elements(pet: dict[str, Any]) -> list[str]:
    primary = _type_label(pet.get("main_type"))
    secondary = _type_label(pet.get("sub_type"))
    return [primary or "普通", secondary or ""]


def _type_label(raw: object) -> str:
    if not isinstance(raw, dict):
        return ""
    zh = str((raw.get("localized") or {}).get("zh", "")).strip()
    if zh in {"首领", "未知", "无"}:
        return ""
    return zh


def _pet_skill_links(
    pet_id: int,
    pet_skill_index: dict[str, Any],
    skill_names_by_id: dict[int, str],
) -> list[dict]:
    entries = pet_skill_index.get("entries", []) if isinstance(pet_skill_index, dict) else []
    by_pet = {int(row.get("pet_id")): row for row in entries if row.get("pet_id") is not None}
    row = by_pet.get(pet_id, {})
    links: list[dict] = []
    for source_type, key in (("技能", "move_pool_ids"), ("可学技能石", "move_stone_ids")):
        for skill_id in row.get(key, []) or []:
            name = skill_names_by_id.get(_int(skill_id))
            if not name:
                continue
            links.append({
                "name": name,
                "source_type": source_type,
                "unlock_level": None,
                "sort_order": len(links),
                "source_id": _int(skill_id),
            })
    return links


def _lineage_key(pet_id: int, pets: list[dict[str, Any]]) -> str:
    by_id = {_int(row.get("id")): row for row in pets}
    cur = by_id.get(pet_id)
    seen: set[int] = set()
    while cur and _int(cur.get("evolves_from_id")) > 0 and _int(cur.get("evolves_from_id")) not in seen:
        seen.add(_int(cur.get("id")))
        parent = by_id.get(_int(cur.get("evolves_from_id")))
        if parent is None:
            break
        cur = parent
    return _pet_display_name(cur or by_id.get(pet_id, {"name": str(pet_id)}))


def _pet_display_name(pet: dict[str, Any]) -> str:
    return str(((pet.get("localized") or {}).get("zh") or {}).get("name") or pet.get("name") or pet.get("id")).strip()


def _form_name(pet: dict[str, Any]) -> str:
    form = str(pet.get("form", "") or "").strip()
    return "" if form == "default" else form


def _range_text(low: object, high: object) -> str:
    if low in (None, "") and high in (None, ""):
        return ""
    return f"{low or ''}-{high or ''}".strip("-")


def _desc_notes(rows: dict[str, dict[str, Any]]) -> dict[int, str]:
    return {_int(k): str(v.get("note", "") or "") for k, v in rows.items()}


def _clean_desc(text: object, desc_notes: dict[int, str]) -> str:
    raw = str(text or "")
    def repl(match: re.Match[str]) -> str:
        desc_id = _int(match.group(1))
        inner = match.group(2)
        return inner or desc_notes.get(desc_id, "")
    raw = DESC_ID_RE.sub(repl, raw)
    raw = TAG_RE.sub("", raw)
    return html.unescape(raw).replace("\u3000", " ").strip()


def _clean_name(value: object) -> str:
    return str(value or "").strip()


def _source(kind: str, source_id: int, payload: object) -> dict:
    return {
        "source_hash": content_hash(payload),
        "source_title": f"{kind}:{source_id}",
        "source_kind": f"pak:{kind}",
    }


def _first_int(value: object, default: int = 0) -> int:
    if isinstance(value, list) and value:
        return _int(value[0], default)
    return _int(value, default)


def _int(value: object, default: int = 0) -> int:
    try:
        if value in (None, ""):
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _is_internal_test_skill(row: dict[str, Any]) -> bool:
    sid = _int(row.get("id"))
    name = _clean_name(row.get("name"))
    if sid < 7000000 and row.get("type") == 2:
        return True
    return name.startswith("GM") or "测试" in name or name in {"？？？"}


if __name__ == "__main__":
    main()
