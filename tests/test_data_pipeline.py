import sys
from pathlib import Path

import pytest

import roco.data.fetch_details as fetch_details
import roco.data.fetch_index as fetch_index
import roco.data.fetch_teams as fetch_teams
import roco.data.parse_skills as parse_skills
from roco.data.effect_classifier import refresh_ability_classification, refresh_skill_classification
from roco.data.catalog import compile_catalog
from roco.compiler.artifact import compile_artifacts
from roco.compiler.nrc_compare import project_report
from roco.data.import_db import import_abilities, import_marks, import_pets, import_skills, import_teams
from roco.data.migrate import migrate
from roco.data.utils import content_hash, load_jsonl, with_canonical_hash, write_jsonl
from roco.compiler.effect_model import EffectTag


def _sample_data():
    skills = [
        refresh_skill_classification({"kind": "skill", "name": "火花", "element": "火", "category": "魔攻", "energy": 1, "power": 60, "effect_text": "造成魔伤"}),
        refresh_skill_classification({"kind": "skill", "name": "拍击", "element": "普通", "category": "物攻", "energy": 1, "power": 40, "effect_text": "造成物伤"}),
    ]
    abilities = [
        refresh_ability_classification({"kind": "ability", "name": "诈死", "description": "力竭不扣MP"}),
        refresh_ability_classification({"kind": "ability", "name": "顺风", "description": "若先于敌方攻击，本次技能威力+50%"}),
        refresh_ability_classification({"kind": "ability", "name": "未映射", "description": "这条描述暂未映射到本项目原语"}),
    ]
    pets = [
        _pet("火火", "火", "诈死", 90, "火花", atk_mag=100),
        _pet("风风", "翼", "顺风", 95, "拍击", atk=90),
        _pet("风空", "翼", "", 95, "拍击", atk=90),
        _pet("谜谜", "普通", "未映射", 55, "拍击"),
        _pet("地地", "地面系", "", 50, "拍击"),
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
    assert catalog.skills_by_name["火花"].effects
    assert catalog.ability_effects[catalog.pets_by_name["火火"].ability_id]
    assert catalog.ability_effects[catalog.pets_by_name["风风"].ability_id]
    assert ("未映射", 1) in catalog.unsupported_effect_stats
    unsupported_rows = conn.execute(
        "SELECT COUNT(*) FROM ability_effects WHERE tag_code = ?",
        (EffectTag.UNSUPPORTED.value,),
    ).fetchone()[0]
    gap_rows = conn.execute("SELECT COUNT(*) FROM effect_gaps WHERE source_name = '未映射'").fetchone()[0]
    assert unsupported_rows == 0
    assert gap_rows == 1

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


def test_fetch_index_incremental_marks_missing_and_force_rewrites(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(fetch_index, "INDEX_DIR", tmp_path)
    write_jsonl([
        {"kind": "index", "target": "skills", "title": "火花", "sort_order": 0},
        {"kind": "index", "target": "skills", "title": "旧技能", "sort_order": 1},
    ], tmp_path / "skills.jsonl")

    merged = fetch_index._merge_index_records("skills", ["火花", "新技能"], force=False)
    assert [row["title"] for row in merged] == ["火花", "新技能", "旧技能"]
    assert merged[2]["missing_from_index"] is True

    forced = fetch_index._merge_index_records("skills", ["火花"], force=True)
    assert [row["title"] for row in forced] == ["火花"]
    assert all("missing_from_index" not in row for row in forced)


def test_fetch_details_incremental_preserves_unchanged_rows(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(fetch_details, "RAW_DIR", tmp_path)
    old = {
        "kind": "skill",
        "name": "火花",
        "source_title": "火花",
        "source_kind": "skill",
        "raw_text": "same",
        "source_hash": content_hash({"raw_text": "same"}),
        "fetched_at": "old",
    }
    write_jsonl([old], tmp_path / "skills_raw.jsonl")

    merged = fetch_details._merge_raw_records(
        "skills",
        ["火花", "拍击"],
        ["火花", "拍击"],
        {"火花": "same", "拍击": "new"},
        force=False,
        fetched_at="new",
    )
    assert merged[0]["fetched_at"] == "old"
    assert merged[1]["fetched_at"] == "new"

    changed = fetch_details._merge_raw_records(
        "skills",
        ["火花"],
        ["火花"],
        {"火花": "changed"},
        force=False,
        fetched_at="newer",
    )
    assert changed[0]["source_hash"] == content_hash({"raw_text": "changed"})
    assert changed[0]["fetched_at"] == "newer"


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


def test_parse_skills_preserves_unchanged_canonical_rows(tmp_path: Path, monkeypatch):
    raw_dir = tmp_path / "raw"
    canonical_dir = tmp_path / "canonical"
    monkeypatch.setattr(parse_skills, "RAW_DIR", raw_dir)
    monkeypatch.setattr(parse_skills, "CANONICAL_DIR", canonical_dir)
    monkeypatch.setattr(sys, "argv", ["parse_skills.py"])
    raw_text = "{{技能信息\n|技能名称=火花\n|属性=火\n|技能类别=魔攻\n|耗能=1\n|威力=60\n|效果=造成魔伤\n}}"
    source = {
        "kind": "skill",
        "name": "火花",
        "source_title": "火花",
        "source_kind": "skill",
        "raw_text": raw_text,
        "source_hash": content_hash({"raw_text": raw_text}),
    }
    write_jsonl([source], raw_dir / "skills_raw.jsonl")
    existing = with_canonical_hash(parse_skills.parse_one("火花", raw_text), source)
    existing["sentinel"] = "kept"
    existing = with_canonical_hash(existing)
    write_jsonl([existing], canonical_dir / "skills.jsonl")

    parse_skills.main()

    rows = load_jsonl(canonical_dir / "skills.jsonl")
    assert rows[0]["sentinel"] == "kept"
    assert rows[0]["source_hash"] == source["source_hash"]


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
    classifier = (root / "roco/data/effect_classifier.py").read_text(encoding="utf-8")
    assert "allow_fallback" not in text
    assert "allow_fallback" not in classifier


def test_effect_classifier_entrypoints_stay_thin():
    root = Path(__file__).resolve().parents[1]
    facade = (root / "roco/data/effect_classifier.py").read_text(encoding="utf-8")
    abilities = (root / "roco/compiler/classifiers/abilities.py").read_text(encoding="utf-8")
    rules_path = root / "roco/compiler/classifiers/ability_rules.py"
    assert rules_path.exists()
    assert len(facade.splitlines()) < 80
    assert len(abilities.splitlines()) < 120
    assert "def generated_ability_effects" not in abilities


def test_optional_nrc_compare_report_is_outside_build(tmp_path: Path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "effect_data.py").write_text('SKILL_EFFECTS = {\n    "火花": [],\n}\n', encoding="utf-8")
    (src / "skill_effects_generated.py").write_text('SKILL_EFFECTS_GENERATED = {\n    "不存在技能": [],\n}\n', encoding="utf-8")

    report = project_report(tmp_path)

    assert report["nrc_root"] == str(tmp_path)
    assert report["nrc_skill_name_count"] == 2
    assert "火花" not in report["project_skill_gaps"]


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


def test_used_effect_gaps_fail_after_team_import(tmp_path: Path):
    conn = migrate(reset=True, db_path=tmp_path / "data.db")
    skills, abilities, pets = _sample_data()
    ability_lookup = import_abilities(conn, abilities)
    skill_lookup = import_skills(conn, skills)
    pet_lookup = import_pets(conn, pets, skill_lookup, ability_lookup)

    teams = [{
        "kind": "team",
        "id": "T1",
        "title": "gap team",
        "author": "",
        "type": "PVP",
        "bloodline_magic": "",
        "description": "",
        "upload_date": "",
        "pets": [{"slot": 1, "name": "谜谜", "name_short": "谜谜", "bloodline": "", "nature": "", "ivs": [], "moves": ["拍击"]}],
    }]
    with pytest.raises(RuntimeError, match="unclassified effect gaps"):
        import_teams(conn, teams, pet_lookup, skill_lookup)
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
        (EffectTag.MOISTURE_MARK.value,),
    ).fetchone()[0]
    gaps = conn.execute(
        "SELECT COUNT(*) FROM effect_gaps WHERE source_name = '火花' AND primitive = 'MOISTURE_MARK'"
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
