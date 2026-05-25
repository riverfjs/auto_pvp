import json
import runpy
import sys
from pathlib import Path

import pytest

import roco.data.fetch_teams as fetch_teams
import roco.data.parse_pak as parse_pak
from roco.common.primitive_keys import buff_ref_key
from roco.compiler_v2.timing_keys import pak_cast_moment_key
from roco.data import catalog_compiler
from roco.compiler_v2.static_artifacts.marks import mark_desc_by_idx
from roco.data.utils import load_jsonl, write_jsonl


def _sample_canonical():
    skills = (
        {
            "kind": "skill",
            "name": "火花",
            "element": "火",
            "category": "魔攻",
            "skill_dam_type": 4,
            "energy": 1,
            "power": 60,
            "effect_text": "造成魔伤",
            "flavor_text": "",
            "flags": 0,
            "effect_rows": [],
            "effect_gaps": [],
        },
        {
            "kind": "skill",
            "name": "展示文案技能",
            "element": "普通",
            "category": "状态",
            "skill_dam_type": 0,
            "energy": 1,
            "power": 0,
            "effect_text": "",
            "flavor_text": "这不是机制描述",
            "flags": 0,
            "effect_rows": [],
            "effect_gaps": [],
        },
    )
    abilities = (
        {
            "kind": "ability",
            "name": "诈死",
            "description": "力竭不扣MP",
            "flags": 0,
            "source_version": "",
            "source_fields": {},
            "effect_rows": [],
            "effect_gaps": [],
        },
    )
    pets = (
        {
            "kind": "pet",
            "name": "火火",
            "form_name": "",
            "stage": "",
            "form_type": "",
            "lineage_key": "火火",
            "elements": ["火", ""],
            "ability": "诈死",
            "ability_description": "力竭不扣MP",
            "stats": {"hp": 100, "atk_phys": 80, "atk_mag": 90, "def_phys": 70, "def_mag": 70, "speed": 60},
            "skills": [{"name": "火花", "source_type": "技能", "unlock_level": 1, "sort_order": 0}],
        },
    )
    return {"skills": skills, "abilities": abilities, "pets": pets, "marks": (), "teams": ()}


def test_static_catalog_compiles_from_canonical_records(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(catalog_compiler, "load_canonical_records", lambda _pak_dir: _sample_canonical())
    hot_path, debug_path = catalog_compiler.compile_catalogs(
        tmp_path / "pak",
        hot_path=tmp_path / "hot.py",
        debug_path=tmp_path / "debug.py",
        action_path=tmp_path / "actions.py",
        engine_link_gaps_path=tmp_path / "engine_link_gaps.jsonl",
    )
    hot_text = hot_path.read_text(encoding="utf-8")
    debug_text = debug_path.read_text(encoding="utf-8")
    action_text = (tmp_path / "actions.py").read_text(encoding="utf-8")

    assert "CATALOG_VERSION = 1" in hot_text
    assert "SCHEMA_VERSION = 'kernel-v2'" in hot_text
    assert "SOURCE_HASH = ''" not in hot_text
    assert "PETS =" in hot_text
    assert "SKILL_EFFECT_ROWS =" in hot_text
    assert "PET_NAMES" not in hot_text
    assert "PET_NAMES =" in debug_text
    assert "SKILL_DESCRIPTIONS =" in debug_text
    assert "ABILITY_DESCRIPTIONS =" in debug_text
    assert "ACTIONS =" in action_text
    assert "造成魔伤" in debug_text
    assert "力竭不扣MP" in debug_text

    debug = runpy.run_path(str(debug_path))
    flavor_only_idx = debug["SKILL_IDS_BY_NAME"]["展示文案技能"]
    assert debug["SKILL_DESCRIPTIONS"][flavor_only_idx] == ""
    assert debug["SKILL_EFFECT_TEXTS"][flavor_only_idx] == ""
    assert debug["SKILL_FLAVOR_TEXTS"][flavor_only_idx] == "这不是机制描述"


def test_static_catalog_rejects_noop_effect_rows(tmp_path: Path, monkeypatch):
    canonical = _sample_canonical()
    bad_skill = dict(canonical["skills"][0])
    bad_skill["effect_rows"] = [("", 11, 1, 10000, 0, 0, 0, 0)]
    canonical["skills"] = (bad_skill,)
    monkeypatch.setattr(catalog_compiler, "load_canonical_records", lambda _pak_dir: canonical)

    with pytest.raises(RuntimeError, match="empty effect primitive"):
        catalog_compiler.compile_catalogs(
            tmp_path / "pak",
            hot_path=tmp_path / "hot.py",
            debug_path=tmp_path / "debug.py",
            action_path=tmp_path / "actions.py",
            engine_link_gaps_path=tmp_path / "engine_link_gaps.jsonl",
        )


def test_static_catalog_records_inert_engine_links(tmp_path: Path, monkeypatch):
    canonical = _sample_canonical()
    skill = dict(canonical["skills"][0])
    skill["effect_rows"] = [
        (buff_ref_key(20231140), pak_cast_moment_key(6), 1, 10000, 1, 0, 0, 0),
        (buff_ref_key(20010792), pak_cast_moment_key(11), 1, 10000, 1, 0, 0, 0),
    ]
    canonical["skills"] = (skill, canonical["skills"][1])
    monkeypatch.setattr(catalog_compiler, "load_canonical_records", lambda _pak_dir: canonical)

    hot_path, _debug_path = catalog_compiler.compile_catalogs(
        tmp_path / "pak",
        hot_path=tmp_path / "hot.py",
        debug_path=tmp_path / "debug.py",
        action_path=tmp_path / "actions.py",
        engine_link_gaps_path=tmp_path / "engine_link_gaps.jsonl",
        engine_link_inert_path=tmp_path / "engine_link_inert.jsonl",
    )

    hot = runpy.run_path(str(hot_path))
    inert_rows = [
        json.loads(line)
        for line in (tmp_path / "engine_link_inert.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert hot["SKILL_EFFECT_ROWS"] == ()
    assert (tmp_path / "engine_link_gaps.jsonl").read_text(encoding="utf-8") == ""
    assert [row["reason"] for row in inert_rows] == [
        "bft_inc_dam_by_skill_zero",
        "bft_attr_change_zero_delta",
    ]


def test_jsonl_roundtrip_is_one_entity_per_line(tmp_path: Path):
    path = tmp_path / "skills.jsonl"
    count = write_jsonl([
        {"kind": "skill", "name": "火花"},
        {"kind": "skill", "name": "拍击"},
    ], path)
    assert count == 2
    assert path.read_text(encoding="utf-8").count("\n") == 2
    assert load_jsonl(path) == [{"kind": "skill", "name": "火花"}, {"kind": "skill", "name": "拍击"}]


def test_parse_pak_generates_canonical_from_extracted_tables(tmp_path: Path, monkeypatch):
    pak = tmp_path / "pak"
    bindata = pak / "BinData"
    bindata.mkdir(parents=True)
    _write_table(bindata / "SKILL_CONF.json", {
        "7020880": {
            "id": 7020880,
            "name": "拍击",
            "desc": "造成魔伤。",
            "energy_cost": [1],
            "dam_para": [65],
            "Skill_Type": 1,
            "damage_type": 3,
            "skill_dam_type": 2,
            "monitor_data_version": 1,
        },
        "200076": {
            "id": 200076,
            "name": "氧循环",
            "desc": "使用草系技能后，回复10%生命。",
            "energy_cost": [0],
            "dam_para": [0],
            "type": 2,
            "damage_type": 1,
            "skill_dam_type": 1,
            "monitor_data_version": 1,
        },
    })
    _write_table(bindata / "PETBASE_CONF.json", {
        "3001": {
            "id": 3001,
            "name": "喵喵",
            "pet_feature": 200076,
            "hp_max_race": 63,
            "phy_attack_race": 57,
            "spe_attack_race": 57,
            "phy_defence_race": 56,
            "spe_defence_race": 59,
            "speed_race": 33,
            "stage": 1,
            "description": "喜欢阳光。",
        }
    })
    _write_table(bindata / "DESC_NOTE_CONF.json", {
        str(1000 + idx.value): {
            "id": 1000 + idx.value,
            "note": note,
            "desc": f"{idx.name.lower()} effect",
        }
        for idx, note in mark_desc_by_idx().items()
    })
    (pak / "moves.json").write_text(
        '[{"id":7020880,"name":"拍击","move_type":{"localized":{"zh":"普通"}},"move_category":"Magic Attack","energy_cost":1,"power":65,"description":"造成魔伤。"}]',
        encoding="utf-8",
    )
    (pak / "Pets.json").write_text(
        '[{"id":3001,"name":"miaomiao","localized":{"zh":{"name":"喵喵"}},"main_type":{"localized":{"zh":"草"}},"sub_type":null,"base_hp":63,"base_phy_atk":57,"base_mag_atk":57,"base_phy_def":56,"base_mag_def":59,"base_spd":33,"is_leader_form":false,"evolves_from_id":null}]',
        encoding="utf-8",
    )
    (pak / "PetSkillIndex.json").write_text(
        '{"entries":[{"pet_id":3001,"move_pool_ids":[7020880],"move_stone_ids":[]}],"skills":[]}',
        encoding="utf-8",
    )
    out = tmp_path / "canonical"
    monkeypatch.setattr(sys, "argv", ["parse_pak.py", "--pak-dir", str(pak), "--out-dir", str(out)])

    parse_pak.main()

    skills = load_jsonl(out / "skills.jsonl")
    abilities = load_jsonl(out / "abilities.jsonl")
    pets = load_jsonl(out / "pets.jsonl")
    marks = load_jsonl(out / "marks.jsonl")
    assert skills[0]["source_kind"] == "pak:skill"
    assert skills[0]["name"] == "拍击"
    assert skills[0]["category"] == "魔攻"
    assert "effect_rows" in skills[0]
    assert abilities[0]["source_kind"] == "pak:ability"
    assert abilities[0]["description"] == "使用草系技能后，回复10%生命。"
    assert pets[0]["source_kind"] == "pak:pet"
    assert pets[0]["ability"] == "氧循环"
    assert marks[0]["source_kind"] == "pak:mark"


def test_pak_move_record_overrides_reversed_skill_conf_name_desc():
    record = parse_pak._skill_record(
        {
            "id": 7040370,
            "name": "对敌方精灵造成魔法伤害。",
            "desc": "火焰箭",
            "Skill_Type": 1,
            "damage_type": 2,
            "skill_dam_type": 4,
            "energy_cost": [2],
            "dam_para": [80],
            "_move_record": {
                "id": 7040370,
                "name": "火焰箭",
                "description": "对敌方精灵造成魔法伤害。",
                "move_type": {"localized": {"zh": "火"}},
                "move_category": "Physical Attack",
                "energy_cost": 2,
                "power": 80,
                "localized": {"zh": {"name": "火焰箭", "description": "对敌方精灵造成魔法伤害。"}},
            },
        },
        {},
    )

    assert record["name"] == "火焰箭"
    assert record["effect_text"] == "对敌方精灵造成魔法伤害。"


def test_pet_skill_links_include_legacy_move_ids():
    links = parse_pak._pet_skill_links(
        3071,
        {
            "entries": [{
                "pet_id": 3071,
                "move_pool_ids": [7020780],
                "move_stone_ids": [7180270],
                "legacy_move_ids": [7040370],
            }],
        },
        {7020780: "防御", 7180270: "诋毁", 7040370: "火焰箭"},
    )

    assert [(link["source_id"], link["name"], link["source_type"]) for link in links] == [
        (7020780, "防御", "技能"),
        (7180270, "诋毁", "可学技能石"),
        (7040370, "火焰箭", "血脉技能"),
    ]


def test_fetch_teams_incremental_merges_by_page_id(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(fetch_teams, "RAW_DIR", tmp_path)
    unchanged = fetch_teams._team_raw_record(
        "101",
        {"fulltext": "队伍A", "fullurl": "url-a", "printouts": {"阵容标题": ["队伍A"]}},
        "old",
    )
    missing = fetch_teams._team_raw_record(
        "102",
        {"fulltext": "队伍B", "fullurl": "url-b", "printouts": {"阵容标题": ["队伍B"]}},
        "old",
    )
    write_jsonl([unchanged, missing], tmp_path / "teams_raw.jsonl")
    incoming = [
        fetch_teams._team_raw_record(
            "101",
            {"fulltext": "队伍A", "fullurl": "url-a", "printouts": {"阵容标题": ["队伍A"]}},
            "new",
        )
    ]

    merged = fetch_teams._merge_team_records(incoming, force=False)
    assert merged[0]["fetched_at"] == "old"
    assert merged[1]["page_id"] == "102"
    assert merged[1]["missing_from_index"] is True

    forced = fetch_teams._merge_team_records(incoming, force=True)
    assert [row["page_id"] for row in forced] == ["101"]


def test_old_db_pipeline_is_deleted():
    root = Path(__file__).resolve().parents[1]
    deleted = [
        "_db",
        "roco/data/build_db.py",
        "roco/data/catalog.py",
        "roco/data/import_db.py",
        "roco/data/migrate.py",
        "roco/data/validation.py",
    ]
    assert [path for path in deleted if (root / path).exists()] == []


def test_non_team_bwiki_data_entrypoints_are_retired():
    root = Path(__file__).resolve().parents[1]
    retired = [
        "roco/data/fetch_index.py",
        "roco/data/fetch_details.py",
        "roco/data/parse_pets.py",
        "roco/data/parse_skills.py",
        "roco/data/parse_marks.py",
        "scripts",
    ]
    assert [path for path in retired if (root / path).exists()] == []


def test_old_classifier_pipeline_is_deleted():
    root = Path(__file__).resolve().parents[1]
    deleted = [
        "roco/data/effect_classifier.py",
        "roco/compiler_v2/classifiers",
        "roco/compiler_v2/effect_compile.py",
        "roco/compiler_v2/skill_tags.py",
        "roco/compiler_v2/effect_registry.py",
    ]
    assert [p for p in deleted if (root / p).exists()] == []


def test_core_pet_naming_guard():
    legacy = "Poke" + "mon"
    forbidden = ("Persistent" + legacy, "Active" + legacy, legacy)
    root = Path(__file__).resolve().parents[1]
    targets = [root / "roco", root / "tests", root / "README.md"]
    offenders: list[str] = []
    for target in targets:
        files = [target] if target.is_file() else [
            p for p in target.rglob("*.py")
            if "__pycache__" not in p.parts and p.name != Path(__file__).name
        ]
        for path in files:
            text = path.read_text(encoding="utf-8")
            if any(word in text for word in forbidden):
                offenders.append(str(path.relative_to(root)))
    assert offenders == []


def test_no_legacy_mark_engineering_name_guard():
    root = Path(__file__).resolve().parents[1]
    offenders: list[str] = []
    for base in (root / "roco", root / "tests"):
        for path in base.rglob("*.py"):
            if "__pycache__" not in path.parts and path.name != Path(__file__).name:
                text = path.read_text(encoding="utf-8")
                legacy = "yin" + "ji"
                if legacy in text or legacy.upper() in text:
                    offenders.append(str(path.relative_to(root)))
    assert offenders == []


def test_skill_effect_rows_have_nonempty_primitive_key():
    if not (parse_pak.DEFAULT_PAK_DATA_DIR / "BinData" / "EFFECT_CONF.json").exists():
        pytest.skip("pak data not extracted")

    canonical = catalog_compiler.load_canonical_records()
    offenders = [
        (record["kind"], record["name"], row)
        for collection in ("skills", "abilities")
        for record in canonical[collection]
        for row in record.get("effect_rows", ()) or ()
        if not row[0]
    ]
    assert offenders == []


def _write_table(path: Path, rows: dict[str, dict]) -> None:
    path.write_text(
        '{"RocoDataRows":' + json.dumps(rows, ensure_ascii=False, separators=(",", ":")) + "}",
        encoding="utf-8",
    )
