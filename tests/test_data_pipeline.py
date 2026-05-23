import json
import sys
from pathlib import Path

import pytest

import roco.data.fetch_teams as fetch_teams
import roco.data.parse_pak as parse_pak
from roco.data.catalog import compile_catalog
from roco.compiler_v2.artifact import compile_artifacts
from roco.data.import_db import import_abilities, import_marks, import_pets, import_skills, import_teams
from roco.data.migrate import migrate
from roco.data.utils import content_hash, load_jsonl, write_jsonl
from roco.generated.canonical_adapters import CANONICAL_MARK_DEFS


def _sample_data():
    skills = [
        {"kind": "skill", "name": "火花", "element": "火", "category": "魔攻", "energy": 1, "power": 60, "effect_text": "造成魔伤", "flags": 0, "effects": [], "effect_rows": [], "classification": {"status": "ok", "source": "pak"}},
        {"kind": "skill", "name": "拍击", "element": "普通", "category": "物攻", "energy": 1, "power": 40, "effect_text": "造成物伤", "flags": 0, "effects": [], "effect_rows": [], "classification": {"status": "ok", "source": "pak"}},
    ]
    abilities = [
        {"kind": "ability", "name": "诈死", "description": "力竭不扣MP", "flags": 0, "effects": [], "effect_rows": [], "classification": {"status": "ok", "source": "pak"}},
        {"kind": "ability", "name": "顺风", "description": "若先于敌方攻击，本次技能威力+50%", "flags": 0, "effects": [], "effect_rows": [], "classification": {"status": "ok", "source": "pak"}},
        {"kind": "ability", "name": "未映射", "description": "这条描述暂未映射到本项目原语", "flags": 0, "effects": [], "effect_rows": [], "classification": {"status": "ok", "source": "pak"}},
    ]
    pets = [
        _pet("火火", "火", "诈死", 90, "火花", atk_mag=100),
        _pet("风风", "翼", "顺风", 95, "拍击", atk=90),
        _pet("风空", "翼", "", 95, "拍击", atk=90),
        _pet("谜谜", "普通", "未映射", 55, "拍击"),
        _pet("地地", "地", "", 50, "拍击"),
    ]
    return skills, abilities, pets


def _pet(name, element, ability, speed, skill, *, atk=80, atk_mag=70):
    ability_descriptions = {
        "诈死": "力竭不扣MP",
        "顺风": "若先于敌方攻击，本次技能威力+50%",
        "未映射": "这条描述暂未映射到本项目原语",
    }
    return {
        "kind": "pet",
        "name": name,
        "form_name": "",
        "stage": "",
        "form_type": "",
        "lineage_key": name,
        "elements": [element, ""],
        "ability": ability,
        "ability_description": ability_descriptions.get(ability, ""),
        "stats": {"hp": 100, "atk_phys": atk, "atk_mag": atk_mag, "def_phys": 70, "def_mag": 70, "speed": speed},
        "height": "",
        "weight": "",
        "distribution": "",
        "description": "",
        "is_shiny": False,
        "evolution_cond": "",
        "source_version": "",
        "skills": [{"name": skill, "source_type": "技能", "unlock_level": 1, "sort_order": 0}],
    }


def test_migrate_import_compile_catalog(tmp_path: Path):
    conn = migrate(reset=True, db_path=tmp_path / "data.db")
    skills, abilities, pets = _sample_data()
    ability_lookup = import_abilities(conn, abilities)
    skill_lookup = import_skills(conn, skills)
    import_pets(conn, pets, skill_lookup, ability_lookup)
    conn.commit()

    catalog = compile_catalog(conn)
    assert catalog.pets_by_name["地地"].types == ("地", "")
    assert catalog.skills_by_name["火花"].element == "火"
    assert len(catalog.pets_by_id) == 5
    assert len(catalog.skills_by_id) == 2

    conn.close()


def test_sqlite_compiles_hot_and_debug_kernel_artifacts(tmp_path: Path):
    db_path = tmp_path / "data.db"
    conn = migrate(reset=True, db_path=db_path)
    skills, abilities, pets = _sample_data()
    ability_lookup = import_abilities(conn, abilities)
    skill_lookup = import_skills(conn, skills)
    import_pets(conn, pets, skill_lookup, ability_lookup)
    conn.commit()
    conn.close()

    hot_path, debug_path = compile_artifacts(
        db_path,
        hot_path=tmp_path / "catalog_hot.py",
        debug_path=tmp_path / "catalog_debug.py",
    )
    hot_text = hot_path.read_text(encoding="utf-8")
    debug_text = debug_path.read_text(encoding="utf-8")

    assert "CATALOG_VERSION = 1" in hot_text
    assert "SCHEMA_VERSION = 'kernel-v1'" in hot_text
    assert "SOURCE_HASH = ''" not in hot_text
    assert "PETS =" in hot_text
    assert "SKILL_EFFECT_ROWS =" in hot_text
    assert "LEADER_FORM_BY_PET =" in hot_text
    assert "PET_NAMES" not in hot_text
    assert "PET_NAMES =" in debug_text
    assert "PET_IDS_BY_NAME =" in debug_text


def test_import_rejects_legacy_structured_elements(tmp_path: Path):
    conn = migrate(reset=True, db_path=tmp_path / "data.db")
    with pytest.raises(ValueError):
        import_skills(conn, [{
            "kind": "skill", "name": "旧属性技能", "element": "钢", "category": "物攻",
            "energy": 1, "power": 1, "effect_text": "", "flags": 0,
            "effects": [], "classification": {"status": "ok", "gaps": []},
        }])
    conn.close()


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
        str(desc_id): {"id": desc_id, "note": f"mark_{code}", "desc": f"{code} effect"}
        for desc_id, code, _, _ in CANONICAL_MARK_DEFS
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


def test_import_db_does_not_read_legacy_parsed_json():
    root = Path(__file__).resolve().parents[1]
    for rel in ("roco/data/import_db.py", "roco/data/build_db.py"):
        text = (root / rel).read_text(encoding="utf-8")
        assert "PARSED_DIR" not in text
        assert "effects.json" not in text
        assert "_data/parsed" not in text
        assert ("yin" + "ji") not in text


def test_build_db_has_no_fallback_classifier_path():
    root = Path(__file__).resolve().parents[1]
    text = (root / "roco/data/build_db.py").read_text(encoding="utf-8")
    assert "allow_fallback" not in text


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


def _write_table(path: Path, rows: dict[str, dict]) -> None:
    path.write_text(
        '{"RocoDataRows":' + json.dumps(rows, ensure_ascii=False, separators=(",", ":")) + "}",
        encoding="utf-8",
    )


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




def test_pets_with_ability_require_description(tmp_path: Path):
    conn = migrate(reset=True, db_path=tmp_path / "data.db")
    skills, abilities, pets = _sample_data()
    ability_lookup = import_abilities(conn, abilities)
    skill_lookup = import_skills(conn, skills)
    bad = dict(pets[0])
    bad["ability_description"] = ""
    with pytest.raises(ValueError, match="empty ability_description"):
        import_pets(conn, [bad], skill_lookup, ability_lookup)
    conn.close()


def test_team_import_succeeds_without_gap_system(tmp_path: Path):
    conn = migrate(reset=True, db_path=tmp_path / "data.db")
    skills, abilities, pets = _sample_data()
    ability_lookup = import_abilities(conn, abilities)
    skill_lookup = import_skills(conn, skills)
    pet_lookup = import_pets(conn, pets, skill_lookup, ability_lookup)

    teams = [{
        "kind": "team",
        "id": "T1",
        "title": "test team",
        "author": "",
        "type": "PVP",
        "bloodline_magic": "",
        "description": "",
        "upload_date": "",
        "pets": [{"slot": 1, "name": "谜谜", "name_short": "谜谜", "bloodline": "", "nature": "", "ivs": [], "moves": ["拍击"]}],
    }]
    import_teams(conn, teams, pet_lookup, skill_lookup)
    count = conn.execute("SELECT COUNT(*) FROM teams").fetchone()[0]
    assert count == 1
    conn.close()


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


def test_marks_import_only_audits_source_skills(tmp_path: Path):
    conn = migrate(reset=True, db_path=tmp_path / "data.db")
    skills, abilities, pets = _sample_data()
    ability_lookup = import_abilities(conn, abilities)
    skill_lookup = import_skills(conn, skills)
    import_pets(conn, pets, skill_lookup, ability_lookup)

    import_marks(conn, [{
        "kind": "mark",
        "code": "moisture",
        "name": "湿润印记",
        "polarity": "positive",
        "packed_index": 0,
        "stacking": "stack_same_mark_replace_same_polarity",
        "effect_text": "全技能能耗-1。",
        "effects": [],
        "mechanism": [],
        "source_skills": [{"skill": "火花", "description": "自己获得1层湿润印记。"}],
    }])

    tag_rows = conn.execute(
        "SELECT COUNT(*) FROM skill_effects WHERE tag_code = ?",
        (2143,),
    ).fetchone()[0]
    gaps = conn.execute(
        "SELECT COUNT(*) FROM effect_gaps WHERE source_name = '火花' AND primitive = '2143'"
    ).fetchone()[0]
    assert tag_rows == 0
    assert gaps == 1
    conn.close()


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


def test_used_gap_fails_strict_validation(tmp_path: Path):
    """A used + unsupported effect must trip ``assert_no_blocking_effect_gaps``."""
    import sqlite3
    from roco.data.validation import assert_no_blocking_effect_gaps

    conn = migrate(reset=True, db_path=tmp_path / "data.db")
    conn.execute("INSERT INTO abilities (name, description) VALUES (?, ?)", ("某ability", "desc"))
    conn.execute(
        "INSERT INTO effect_gaps (source_type, source_name, primitive, params_json, reason, used_count) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("ability", "某ability", "effect_9999", "{}", "effect_type_3_state_change", 5),
    )
    with pytest.raises(RuntimeError, match=r"used effect_gaps row\(s\) have no acknowledgement"):
        assert_no_blocking_effect_gaps(conn)
    conn.close()


def test_kernel_noop_row_fails_validation(tmp_path: Path):
    """Defensive: ``assert_no_kernel_noop_rows`` rejects tag_code=0 rows.

    Inserts a synthetic tag_code=0 row directly into ``skill_effects`` and
    confirms the validator surfaces it.  Catches regressions where a
    decoder bug lets H_NOOP=0 leak into runtime tables.
    """
    from roco.data.validation import assert_no_kernel_noop_rows

    conn = migrate(reset=True, db_path=tmp_path / "data.db")
    conn.execute(
        "INSERT INTO skills (name, element_id, category_code, category_name, energy, power, flags) "
        "VALUES (?, 0, 1, '物攻', 1, 50, 0)",
        ("某skill",),
    )
    sid = conn.execute("SELECT id FROM skills WHERE name = ?", ("某skill",)).fetchone()[0]
    conn.execute(
        "INSERT INTO skill_effects (skill_id, timing_code, tag_code, params_json, sort_order) "
        "VALUES (?, 11, 0, '{}', 0)",
        (sid,),
    )
    with pytest.raises(RuntimeError, match="kernel noop rows leaked"):
        assert_no_kernel_noop_rows(conn)
    conn.close()


def test_skill_effects_no_tag_code_zero_invariant(tmp_path: Path):
    """After a clean build (allowing used gaps), no runtime row may carry tag_code=0.

    Builds a tmp DB rather than reading the repo's _db so this test is
    independent of stale on-disk artifacts.  Counts both skill_effects and
    ability_effects.
    """
    import sqlite3
    from roco.data.parse_pak import PakData, build_skills, build_abilities, _desc_notes, DEFAULT_PAK_DATA_DIR
    from roco.compiler_v2.effect_codegen import PakTables
    from roco.data.import_db import import_abilities, import_skills

    if not (DEFAULT_PAK_DATA_DIR / "BinData" / "EFFECT_CONF.json").exists():
        pytest.skip("pak data not extracted")

    data = PakData(DEFAULT_PAK_DATA_DIR)
    pak_tables = PakTables(data.root)
    desc_notes = _desc_notes(data.desc_note_conf)
    skills, _ = build_skills(data, desc_notes, pak_tables)
    abilities, _ = build_abilities(data, desc_notes, pak_tables)

    conn = migrate(reset=True, db_path=tmp_path / "data.db")
    import_abilities(conn, abilities)
    import_skills(conn, skills)
    conn.commit()

    skill_noops = conn.execute("SELECT COUNT(*) FROM skill_effects WHERE tag_code = 0").fetchone()[0]
    ability_noops = conn.execute("SELECT COUNT(*) FROM ability_effects WHERE tag_code = 0").fetchone()[0]
    conn.close()
    assert skill_noops == 0, f"{skill_noops} skill_effects rows have tag_code=0"
    assert ability_noops == 0, f"{ability_noops} ability_effects rows have tag_code=0"


def _jsonl_records(path: Path):
    """Iterate JSONL rows, mirroring loader behaviour (skip empty + ``#`` comments)."""
    with path.open("r", encoding="utf-8") as fp:
        for line_no, raw in enumerate(fp, 1):
            raw = raw.strip()
            if not raw or raw.startswith("#"):
                continue
            yield line_no, json.loads(raw)


def test_exact_effects_jsonl_removed_from_pipeline():
    """Exact effect rules now live in family decoders / generated tables."""
    path = Path(__file__).resolve().parents[1] / "roco" / "compiler_v2" / "rules" / "exact_effects.jsonl"
    assert not path.exists()


def test_prefix_handlers_jsonl_removed_from_pipeline():
    """Prefix/base-id handler axes now live on engine op_meta decorators."""
    path = Path(__file__).resolve().parents[1] / "roco" / "compiler_v2" / "rules" / "prefix_handlers.jsonl"
    assert not path.exists()
