from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from roco.compiler_v2.build import build_static_bundle
from roco.compiler_v2.emit import write_static_files
from roco.compiler_v2.sources import DEFAULT_LUA_ROOT, parse_lua_enums


def test_lua_enum_parser_reads_real_battle_enums():
    text = (DEFAULT_LUA_ROOT / "Data" / "Config" / "Enum.lua").read_text(encoding="utf-8")

    enums = parse_lua_enums(text, {"EffectType", "BuffType", "SkillDamType", "WeatherType"})

    assert enums["EffectType"]["ET_COUNTER"] == 31
    assert enums["BuffType"]["BFT_FREEZE"] == 58
    assert enums["SkillDamType"]["SDT_WATER"] == 5
    assert enums["WeatherType"]["WT_SANDSTORM"] == 6


def test_lua_enum_parser_rejects_duplicate_keys():
    text = "Enum.X = setmetatable({ A = 1, A = 2 }, EnumMeta)"

    with pytest.raises(ValueError, match="declares 'A' more than once"):
        parse_lua_enums(text)


def test_static_bundle_joins_pak_axes_with_lua_names():
    bundle = build_static_bundle()

    assert bundle.effect_order_names[31] == "ET_COUNTER"
    assert bundle.effect_order_counts[31] > 0
    assert bundle.buffbase_order_names[58] == "BFT_FREEZE"
    assert bundle.buffbase_order_counts[58] > 0
    assert bundle.skill_dam_type_names[5] == "SDT_WATER"
    assert bundle.skill_dam_type_to_element_name[5] == "水"
    assert bundle.skill_dam_type_to_element_name[7] == "地"
    assert bundle.skill_dam_type_to_element[7] == bundle.skill_dam_type_to_element[8]
    assert bundle.skill_dam_type_unmapped[21] == "SDT_RELAX"
    assert "battle_pvp_level" in bundle.battle_global_nums
    assert bundle.source_hash


def test_static_files_are_importable_python(tmp_path: Path):
    bundle = build_static_bundle()
    written = write_static_files(bundle, tmp_path)

    pak_axes = _import_module(written["pak_axes"], "compiler_v2_test_pak_axes")
    lua_enums = _import_module(written["lua_enums"], "compiler_v2_test_lua_enums")
    manifest = _import_module(written["manifest"], "compiler_v2_test_manifest")

    assert pak_axes.EFFECT_ORDER_NAMES[31] == "ET_COUNTER"
    assert pak_axes.BUFFBASE_ORDER_NAMES[58] == "BFT_FREEZE"
    assert pak_axes.EFFECT_ORDER_COUNTS[31] > 0
    assert pak_axes.BUFFBASE_ORDER_COUNTS[58] > 0
    assert pak_axes.BUFF_BASE_TO_ORDER
    assert lua_enums.EFFECT_TYPE["ET_COUNTER"] == 31
    assert manifest.SOURCE_HASH == bundle.source_hash


def test_generated_runtime_static_adapters_match_bundle():
    bundle = build_static_bundle()

    from roco.generated import battle_globals, bloodline_magic, skill_dam_types, weather_table

    assert battle_globals.BATTLE_GLOBAL_NUMS == bundle.battle_global_nums
    assert skill_dam_types.SKILL_DAM_TYPE_TO_ELEMENT == bundle.skill_dam_type_to_element
    assert skill_dam_types.SKILL_DAM_TYPE_TO_ELEMENT_NAME[7] == "地"
    assert weather_table.WEATHER_ROWS[6]["name"] == "沙尘暴"
    assert weather_table.PAK_WEATHER_TYPE_TO_KERNEL[6] == 2
    assert weather_table.PAK_WEATHER_DEFAULT_TURNS[6] == 8
    assert bloodline_magic.PAK_BLOODLINE_LEADER == 19
    assert bloodline_magic.PAK_BLOODLINE_POLLUTANT == 23
    assert bloodline_magic.PAK_ELEMENT_TO_BLOODLINE[0] == 1
    assert bloodline_magic.PLAYER_MAGIC_WILLPOWER_ID == 100002
    assert bloodline_magic.PLAYER_MAGIC_LEADER_TRANSFORM_ID == 100007
    assert bloodline_magic.WILLPOWER_RUNTIME_SKILL_BY_BLOODLINE_ID[1][4] == 80
    assert bloodline_magic.WILLPOWER_COUNTER_STATUS_BPS == 25000


def test_compiler_v2_has_no_semantics_table_module():
    path = Path(__file__).resolve().parents[1] / "roco" / "compiler_v2" / "semantics.py"
    assert not path.exists()


def _import_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
