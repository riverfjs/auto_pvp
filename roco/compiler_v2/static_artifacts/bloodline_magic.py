from __future__ import annotations

from typing import Any

from roco.common.enums import ELEMENT_NAMES, SkillCategory
from roco.compiler_v2.build import build_static_bundle
from roco.compiler_v2.model import StaticBundle

from .common import BLOODLINE_MAGIC_PATH, PAK_BIN, _assign, _first_int, _load_json_table, _maybe_int


def _skill_category_code_from_pak(row: dict[str, Any]) -> int:
    skill_type = _maybe_int(row.get("Skill_Type")) or 0
    damage_type = _maybe_int(row.get("damage_type")) or 0
    if skill_type == 3:
        return SkillCategory.DEFENSE.value
    if skill_type == 2:
        return SkillCategory.STATUS.value
    if damage_type == 2:
        return SkillCategory.PHYSICAL.value
    if damage_type in {3, 4}:
        return SkillCategory.MAGICAL.value
    return SkillCategory.STATUS.value

def _target_blood_limit(row: dict[str, Any]) -> tuple[int, ...]:
    return tuple(
        int(value)
        for value in row.get("target_blood_limit") or ()
        if _maybe_int(value) is not None
    )

def _effect_params(effect_row: dict[str, Any], slot: int) -> tuple[int, ...]:
    params = effect_row.get("effect_param") or []
    if slot >= len(params) or not isinstance(params[slot], dict):
        return ()
    return tuple(
        int(value)
        for value in params[slot].get("params") or ()
        if _maybe_int(value) is not None
    )

def _counter_response_skill_id(
    skill_row: dict[str, Any],
    effect_rows: dict[int | str, dict],
) -> int | None:
    for result in skill_row.get("skill_result") or ():
        if not isinstance(result, dict):
            continue
        effect_id = _maybe_int(result.get("effect_id"))
        if effect_id is None:
            continue
        effect = effect_rows.get(effect_id)
        if effect is None or int(effect.get("effect_order") or 0) != 31:
            continue
        params = _effect_params(effect, 0)
        if params:
            return params[0]
    return None

def _bag_items_by_player_magic_id(bag_rows: dict[int | str, dict]) -> dict[int, list[tuple[int, dict]]]:
    out: dict[int, list[tuple[int, dict]]] = {}
    for item_id, rec in bag_rows.items():
        if not isinstance(item_id, int):
            continue
        player_magic_id = _maybe_int(rec.get("player_skill_id"))
        if player_magic_id is None:
            continue
        out.setdefault(player_magic_id, []).append((item_id, rec))
    return {key: sorted(items, key=lambda item: item[0]) for key, items in out.items()}

def _primary_bag_item(items: list[tuple[int, dict]]) -> tuple[int, dict] | None:
    if not items:
        return None
    battle_items = [
        item for item in items
        if _maybe_int(item[1].get("can_use_in_battle")) == 1
    ]
    released = [item for item in battle_items if item[1].get("is_release") is True]
    sorted_items = sorted(
        released or battle_items or items,
        key=lambda item: (
            _maybe_int(item[1].get("sort_id")) is None,
            _maybe_int(item[1].get("sort_id")) or 0,
            item[0],
        ),
    )
    return sorted_items[0]

def _magic_kind(
    *,
    name: str,
    target_bloodlines: tuple[int, ...],
    tag: int,
    element_bloodlines: tuple[int, ...],
    leader_bloodline: int,
) -> str:
    if name == "愿力强化" and target_bloodlines == element_bloodlines:
        return "willpower_strike"
    if name == "进化之力" and tag == 1 and target_bloodlines == (leader_bloodline,):
        return "leader_transform"
    return ""

def build_bloodline_magic_tables(bundle: StaticBundle | None = None) -> dict[str, Any]:
    if bundle is None:
        bundle = build_static_bundle()
    blood_rows = _load_json_table(PAK_BIN / "PET_BLOOD_CONF.json")
    player_magic_rows = _load_json_table(PAK_BIN / "PLAYER_MAGIC_CONF.json")
    skill_rows = _load_json_table(PAK_BIN / "SKILL_CONF.json")
    effect_rows = _load_json_table(PAK_BIN / "EFFECT_CONF.json")
    bag_rows = _load_json_table(PAK_BIN / "BAG_ITEM_CONF.json")

    element_by_name = {name: idx for idx, name in enumerate(ELEMENT_NAMES)}
    bloodlines: dict[int, dict[str, Any]] = {}
    pak_to_element: dict[int, int] = {}
    element_to_bloodline: list[int | None] = [None] * len(ELEMENT_NAMES)
    for bloodline_id, rec in sorted(blood_rows.items()):
        if not isinstance(bloodline_id, int):
            continue
        name = str(rec.get("blood_name") or rec.get("name") or "").strip()
        if not name:
            raise RuntimeError(f"PET_BLOOD_CONF {bloodline_id} has empty blood_name")
        element_id = element_by_name.get(name)
        blood_skill = tuple(
            int(value)
            for value in rec.get("blood_skill") or ()
            if _maybe_int(value) is not None
        )
        bloodlines[bloodline_id] = {
            "id": bloodline_id,
            "code": f"bloodline_{bloodline_id}",
            "name": name,
            "display_name": str(rec.get("name") or name).strip(),
            "kind": "element" if element_id is not None else "special",
            "element_id": element_id,
            "pak_blood_type": _maybe_int(rec.get("blood_type")),
            "attribute_type": _maybe_int(rec.get("attribute_type")),
            "blood_skill": blood_skill,
            "tips_desc": str(rec.get("tips_desc") or "").strip(),
        }
        if element_id is not None:
            pak_to_element[bloodline_id] = element_id
            if element_to_bloodline[element_id] is not None:
                raise RuntimeError(
                    f"duplicate PET_BLOOD_CONF element {name!r}: "
                    f"{element_to_bloodline[element_id]} and {bloodline_id}"
                )
            element_to_bloodline[element_id] = bloodline_id

    missing_elements = [
        name for idx, name in enumerate(ELEMENT_NAMES)
        if element_to_bloodline[idx] is None
    ]
    if missing_elements:
        raise RuntimeError(f"PET_BLOOD_CONF missing element bloodlines: {missing_elements}")

    bloodline_by_name = {row["name"]: bloodline_id for bloodline_id, row in bloodlines.items()}
    leader_bloodline = bloodline_by_name.get("首领")
    pollutant_bloodline = bloodline_by_name.get("污染")
    if leader_bloodline is None:
        raise RuntimeError("PET_BLOOD_CONF missing 首领 bloodline")
    if pollutant_bloodline is None:
        raise RuntimeError("PET_BLOOD_CONF missing 污染 bloodline")

    willpower_skill_by_bloodline: dict[int, int] = {}
    willpower_runtime_skill_by_bloodline: dict[int, tuple[int, int, int, int, int, int, int, int]] = {}
    willpower_counter_bps: set[int] = set()
    willpower_powers: set[int] = set()
    for bloodline_id in sorted(pak_to_element):
        bloodline = bloodlines[bloodline_id]
        skill_ids = bloodline["blood_skill"]
        if not skill_ids:
            raise RuntimeError(f"PET_BLOOD_CONF {bloodline_id} has no blood_skill")
        skill_id = int(skill_ids[0])
        skill = skill_rows.get(skill_id)
        if skill is None:
            raise RuntimeError(f"PET_BLOOD_CONF {bloodline_id} references missing skill {skill_id}")
        skill_dam_type = int(skill.get("skill_dam_type") or 0)
        element_id = bundle.skill_dam_type_to_element.get(skill_dam_type)
        if element_id != pak_to_element[bloodline_id]:
            raise RuntimeError(
                f"bloodline {bloodline_id} skill {skill_id} maps to element {element_id}, "
                f"expected {pak_to_element[bloodline_id]}"
            )
        energy = _first_int(skill.get("energy_cost"))
        power = _first_int(skill.get("dam_para"))
        category = _skill_category_code_from_pak(skill)
        hit_count = max(1, _maybe_int(skill.get("skill_time")) or 1)
        willpower_skill_by_bloodline[bloodline_id] = skill_id
        willpower_runtime_skill_by_bloodline[bloodline_id] = (
            0,
            element_id,
            category,
            energy,
            power,
            0,
            hit_count,
            skill_dam_type,
        )
        willpower_powers.add(power)
        counter_skill_id = _counter_response_skill_id(skill, effect_rows)
        if counter_skill_id is not None:
            counter_skill = skill_rows.get(counter_skill_id)
            if counter_skill is None:
                raise RuntimeError(f"willpower skill {skill_id} references missing counter skill {counter_skill_id}")
            counter_power = _first_int(counter_skill.get("dam_para"))
            if power <= 0:
                raise RuntimeError(f"willpower skill {skill_id} has non-positive power {power}")
            willpower_counter_bps.add(counter_power * 10_000 // power)

    if len(willpower_powers) != 1:
        raise RuntimeError(f"willpower blood skills have mixed base powers: {sorted(willpower_powers)}")
    if len(willpower_counter_bps) != 1:
        raise RuntimeError(
            f"willpower counter response ratios are not uniform: {sorted(willpower_counter_bps)}"
        )

    bag_items_by_magic = _bag_items_by_player_magic_id(bag_rows)
    element_bloodlines = tuple(int(v) for v in element_to_bloodline)
    player_magics: dict[int, dict[str, Any]] = {}
    supported_magic_rows: list[tuple[int, str, str, int, str]] = []
    id_by_kind: dict[str, int] = {}
    for magic_id, rec in sorted(player_magic_rows.items()):
        if not isinstance(magic_id, int):
            continue
        skill_id = int(rec.get("skill_id") or 0)
        skill = skill_rows.get(skill_id)
        if skill is None:
            raise RuntimeError(f"PLAYER_MAGIC_CONF {magic_id} references missing skill {skill_id}")
        bag_item = _primary_bag_item(bag_items_by_magic.get(magic_id, []))
        bag_id = bag_item[0] if bag_item is not None else 0
        bag = bag_item[1] if bag_item is not None else {}
        name = str(bag.get("name") or skill.get("name") or "").strip()
        description = str(bag.get("description") or skill.get("desc") or "").strip()
        target_bloodlines = _target_blood_limit(skill)
        tag = int(rec.get("tag") or 0)
        kind = _magic_kind(
            name=name,
            target_bloodlines=target_bloodlines,
            tag=tag,
            element_bloodlines=element_bloodlines,
            leader_bloodline=leader_bloodline,
        )
        code = kind or f"player_magic_{magic_id}"
        uses = int(rec.get("battle_use_time") or 0)
        player_magics[magic_id] = {
            "id": magic_id,
            "code": code,
            "kind": kind,
            "name": name,
            "description": description,
            "skill_id": skill_id,
            "bag_item_id": bag_id,
            "uses_per_battle": uses,
            "cooldown_rounds": int(rec.get("round") or 0),
            "skill_cd_rounds": tuple(
                int(value)
                for value in skill.get("cd_round") or ()
                if _maybe_int(value) is not None
            ),
            "target_bloodlines": target_bloodlines,
            "tag": tag,
        }
        if kind:
            if kind in id_by_kind:
                raise RuntimeError(f"duplicate supported player magic kind {kind!r}")
            id_by_kind[kind] = magic_id
            supported_magic_rows.append((magic_id, code, name, uses, description))

    for required_kind in ("willpower_strike", "leader_transform"):
        if required_kind not in id_by_kind:
            raise RuntimeError(f"PLAYER_MAGIC_CONF missing supported magic kind {required_kind}")

    return {
        "bloodlines": bloodlines,
        "bloodline_db_rows": tuple(
            (
                bloodline_id,
                row["code"],
                row["name"],
                row["kind"],
                row["element_id"],
            )
            for bloodline_id, row in sorted(bloodlines.items())
        ),
        "bloodline_ids_by_name": dict(sorted(bloodline_by_name.items(), key=lambda item: item[1])),
        "pak_bloodline_to_element": dict(sorted(pak_to_element.items())),
        "pak_element_to_bloodline": tuple(int(v) for v in element_to_bloodline),
        "pak_bloodline_leader": leader_bloodline,
        "pak_bloodline_pollutant": pollutant_bloodline,
        "player_magics": player_magics,
        "supported_magic_db_rows": tuple(sorted(supported_magic_rows)),
        "supported_magic_ids_by_name": {
            player_magics[magic_id]["name"]: magic_id
            for magic_id in sorted(id_by_kind.values())
        },
        "player_magic_willpower_id": id_by_kind["willpower_strike"],
        "player_magic_leader_transform_id": id_by_kind["leader_transform"],
        "default_bloodline_magic_name": player_magics[id_by_kind["willpower_strike"]]["name"],
        "willpower_skill_by_bloodline": dict(sorted(willpower_skill_by_bloodline.items())),
        "willpower_runtime_skill_by_bloodline": dict(sorted(willpower_runtime_skill_by_bloodline.items())),
        "willpower_base_power": next(iter(willpower_powers)),
        "willpower_counter_status_bps": next(iter(willpower_counter_bps)),
    }

def write_bloodline_magic(bundle: StaticBundle | None = None) -> dict[str, int]:
    tables = build_bloodline_magic_tables(bundle)
    lines = [
        "# Auto-generated by compiler_v2 from PET_BLOOD_CONF + PLAYER_MAGIC_CONF + BAG_ITEM_CONF + SKILL_CONF -- do not edit.",
        "",
        "from __future__ import annotations",
        "",
    ]
    lines.append(_assign("BLOODLINES_BY_ID", tables["bloodlines"]).rstrip())
    lines.append(_assign("BLOODLINE_DB_ROWS", tables["bloodline_db_rows"]).rstrip())
    lines.append(_assign("BLOODLINE_IDS_BY_NAME", tables["bloodline_ids_by_name"]).rstrip())
    lines.append(_assign("PAK_BLOODLINE_TO_ELEMENT", tables["pak_bloodline_to_element"]).rstrip())
    lines.append(_assign("PAK_ELEMENT_TO_BLOODLINE", tables["pak_element_to_bloodline"]).rstrip())
    lines.append(_assign("PAK_BLOODLINE_LEADER", tables["pak_bloodline_leader"]).rstrip())
    lines.append(_assign("PAK_BLOODLINE_POLLUTANT", tables["pak_bloodline_pollutant"]).rstrip())
    lines.append(_assign("PLAYER_MAGICS_BY_ID", tables["player_magics"]).rstrip())
    lines.append(_assign("BLOODLINE_MAGIC_DB_ROWS", tables["supported_magic_db_rows"]).rstrip())
    lines.append(_assign("BLOODLINE_MAGIC_IDS_BY_NAME", tables["supported_magic_ids_by_name"]).rstrip())
    lines.append(_assign("PLAYER_MAGIC_WILLPOWER_ID", tables["player_magic_willpower_id"]).rstrip())
    lines.append(_assign("PLAYER_MAGIC_LEADER_TRANSFORM_ID", tables["player_magic_leader_transform_id"]).rstrip())
    lines.append(_assign("DEFAULT_BLOODLINE_MAGIC_NAME", tables["default_bloodline_magic_name"]).rstrip())
    lines.append(_assign("WILLPOWER_SKILL_BY_BLOODLINE_ID", tables["willpower_skill_by_bloodline"]).rstrip())
    lines.append(_assign("WILLPOWER_RUNTIME_SKILL_BY_BLOODLINE_ID", tables["willpower_runtime_skill_by_bloodline"]).rstrip())
    lines.append(_assign("WILLPOWER_BASE_POWER", tables["willpower_base_power"]).rstrip())
    lines.append(_assign("WILLPOWER_COUNTER_STATUS_BPS", tables["willpower_counter_status_bps"]).rstrip())
    lines.append("")
    BLOODLINE_MAGIC_PATH.write_text("\n".join(lines), encoding="utf-8")
    return {
        "bloodline_count": len(tables["bloodlines"]),
        "player_magic_count": len(tables["player_magics"]),
        "supported_magic_count": len(tables["supported_magic_db_rows"]),
    }
