"""Build the experimental pak+Lua static bundle."""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
from typing import Any

from roco.common.enums import ELEMENT_NAMES
from roco.compiler_v2.emit import write_static_files
from roco.compiler_v2.model import StaticBundle
from roco.compiler_v2.sources import (
    DEFAULT_LUA_ROOT,
    DEFAULT_PAK_DATA_DIR,
    LuaEnumSource,
    PakSource,
    combined_source_hash,
)


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT_DIR = ROOT / "roco" / "generated" / "static"

DEFAULT_ENUMS = (
    "BattleEvent",
    "BuffGroupSign",
    "BuffType",
    "EffectType",
    "SkillDamType",
    "WeatherType",
)


def build_static_bundle(
    *,
    pak_data_dir: Path = DEFAULT_PAK_DATA_DIR,
    lua_root: Path = DEFAULT_LUA_ROOT,
    enum_names: tuple[str, ...] = DEFAULT_ENUMS,
) -> StaticBundle:
    """Build a pak+Lua static bundle without consulting JSON rule files."""
    pak = PakSource(pak_data_dir)
    lua = LuaEnumSource(lua_root)

    lua_enums = lua.enums(enum_names)
    effect_conf = pak.table("EFFECT_CONF")
    buffbase_conf = pak.table("BUFFBASE_CONF")
    battle_global_conf = pak.table("BATTLE_GLOBAL_CONFIG")
    type_dictionary = pak.table("TYPE_DICTIONARY")
    pak_root = pak.data_dir.parent if pak.data_dir.name == "BinData" else pak.data_dir
    moves_path = pak_root / "moves.json"

    source_files = [
        pak.source_file("EFFECT_CONF"),
        pak.source_file("BUFFBASE_CONF"),
        pak.source_file("BUFF_CONF"),
        pak.source_file("BATTLE_GLOBAL_CONFIG"),
        pak.source_file("TYPE_DICTIONARY"),
        pak.source_file("WEATHER_CONF"),
        pak.source_file("PET_BLOOD_CONF"),
        pak.source_file("PLAYER_MAGIC_CONF"),
        pak.source_file("BAG_ITEM_CONF"),
        pak.source_file("SKILL_CONF"),
        pak.source_file("DESC_NOTE_CONF"),
        pak.source_file("NATURE_CONF"),
        pak.source_file("ATTRIBUTE_CONF"),
        lua.source_file(),
    ]
    if moves_path.exists():
        source_files.append(moves_path)
    source_hash = combined_source_hash(source_files)

    effect_order_counts = _count_int_field(effect_conf.values(), "effect_order")
    buffbase_order_counts = _count_int_field(buffbase_conf.values(), "buffbase_order")

    effect_order_names = _names_for_values(
        effect_order_counts,
        lua_enums["EffectType"],
        fallback_prefix="ET",
    )
    buffbase_order_names = _names_for_values(
        buffbase_order_counts,
        lua_enums["BuffType"],
        fallback_prefix="BFT",
    )

    battle_nums, battle_lists, battle_strings = _battle_globals(battle_global_conf.values())

    buff_base_to_order: dict[int, int] = {}
    for base_id, rec in buffbase_conf.items():
        order = _maybe_int(rec.get("buffbase_order"))
        if isinstance(base_id, int) and order is not None:
            buff_base_to_order[base_id] = order

    skill_dam_type_names = {value: name for name, value in lua_enums["SkillDamType"].items()}
    (
        skill_dam_type_to_element,
        skill_dam_type_to_element_name,
        skill_dam_type_unmapped,
    ) = _skill_dam_type_adapters(lua_enums["SkillDamType"], type_dictionary)

    return StaticBundle(
        source_hash=source_hash,
        source_files=tuple(source_files),
        lua_enums=lua_enums,
        lua_enum_references=lua.enum_references(enum_names),
        battle_global_nums=battle_nums,
        battle_global_lists=battle_lists,
        battle_global_strings=battle_strings,
        skill_dam_type_names=dict(sorted(skill_dam_type_names.items())),
        skill_dam_type_to_element=skill_dam_type_to_element,
        skill_dam_type_to_element_name=skill_dam_type_to_element_name,
        skill_dam_type_unmapped=skill_dam_type_unmapped,
        effect_order_names=effect_order_names,
        effect_order_counts=dict(sorted(effect_order_counts.items())),
        buffbase_order_names=buffbase_order_names,
        buffbase_order_counts=dict(sorted(buffbase_order_counts.items())),
        buff_base_to_order=dict(sorted(buff_base_to_order.items())),
    )


def _maybe_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _count_int_field(rows: Any, field: str) -> dict[int, int]:
    counter: Counter[int] = Counter()
    for rec in rows:
        value = _maybe_int(rec.get(field))
        if value is not None:
            counter[value] += 1
    return dict(sorted(counter.items()))


def _names_for_values(
    counts: dict[int, int],
    enum_values: dict[str, int],
    *,
    fallback_prefix: str,
) -> dict[int, str]:
    by_value = {value: name for name, value in enum_values.items()}
    return {
        value: by_value.get(value, f"{fallback_prefix}_{value}")
        for value in sorted(counts)
    }


def _battle_globals(rows: Any) -> tuple[dict[str, int], dict[str, tuple[int, ...]], dict[str, str]]:
    nums: dict[str, int] = {}
    lists: dict[str, tuple[int, ...]] = {}
    strings: dict[str, str] = {}
    for rec in rows:
        key = rec.get("key")
        if not key:
            continue
        num = _maybe_int(rec.get("num"))
        if num is not None:
            nums[str(key)] = num
        num_list = rec.get("numList")
        if isinstance(num_list, list) and num_list:
            values = tuple(int(v) for v in num_list if _maybe_int(v) is not None)
            if values:
                lists[str(key)] = values
        text = rec.get("str")
        if isinstance(text, str) and text:
            strings[str(key)] = text
    return dict(sorted(nums.items())), dict(sorted(lists.items())), dict(sorted(strings.items()))


def _skill_dam_type_adapters(
    skill_dam_type_enum: dict[str, int],
    type_dictionary: dict[int | str, dict[str, Any]],
) -> tuple[dict[int, int], dict[int, str], dict[int, str]]:
    """Derive pak ``skill_dam_type`` adapters from Lua enum + TYPE_DICTIONARY.

    Most skill damage type ids line up with ``TYPE_DICTIONARY.id``.  The pak
    still ships the deprecated rock row at id=7, while both SDT_EARTH(7) and
    SDT_STONE(8) are runtime ground damage; when a dictionary row is marked
    deprecated, use the next active dictionary row as the canonical element.
    """

    element_index = {name: idx for idx, name in enumerate(ELEMENT_NAMES)}
    type_name_by_id: dict[int, str] = {}
    deprecated_type_ids: set[int] = set()
    for type_id, rec in type_dictionary.items():
        pak_id = _maybe_int(type_id)
        if pak_id is None:
            continue
        short_name = str(rec.get("short_name") or "").strip()
        if not short_name:
            continue
        if "废弃" in short_name:
            deprecated_type_ids.add(pak_id)
            continue
        if short_name in element_index:
            type_name_by_id[pak_id] = short_name

    by_value = {value: name for name, value in skill_dam_type_enum.items()}
    to_element_name: dict[int, str] = {}
    unmapped: dict[int, str] = {}
    for value, enum_name in sorted(by_value.items()):
        element_name = type_name_by_id.get(value)
        if element_name is None and value in deprecated_type_ids:
            element_name = type_name_by_id.get(value + 1)
        if element_name is None:
            unmapped[value] = enum_name
            continue
        to_element_name[value] = element_name

    to_element = {
        value: element_index[element_name]
        for value, element_name in sorted(to_element_name.items())
    }
    return to_element, dict(sorted(to_element_name.items())), dict(sorted(unmapped.items()))


def main() -> None:
    parser = argparse.ArgumentParser(description="Build experimental pak+Lua static compiler outputs.")
    parser.add_argument("--pak-dir", type=Path, default=DEFAULT_PAK_DATA_DIR)
    parser.add_argument("--lua-root", type=Path, default=DEFAULT_LUA_ROOT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args()

    bundle = build_static_bundle(pak_data_dir=args.pak_dir, lua_root=args.lua_root)
    written = write_static_files(bundle, args.out_dir)
    print(f"compiler_v2 source_hash={bundle.source_hash}")
    for name, path in written.items():
        print(f"{name}: {path}")


if __name__ == "__main__":
    main()
