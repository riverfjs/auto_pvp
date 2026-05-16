from pathlib import Path

import pytest

from roco.data.catalog import compile_catalog
from roco.data.import_db import import_abilities, import_pets, import_skills
from roco.data.migrate import migrate
from roco.engine.battle import BattleEngine
from roco.engine.state import MoveDecision


def _sample_data():
    skills = {
        "火花": {"技能名称": "火花", "属性": "火", "技能类别": "魔攻", "耗能": 1, "威力": 60, "效果": "造成魔伤"},
        "拍击": {"技能名称": "拍击", "属性": "普通", "技能类别": "物攻", "耗能": 1, "威力": 40, "效果": "造成物伤"},
    }
    pets = {
        "火火": {
            "主属性": "火", "2属性": "", "特性": "诈死", "特性描述": "力竭不扣MP",
            "生命": 100, "物攻": 80, "魔攻": 100, "物防": 70, "魔防": 70, "速度": 90,
            "技能": ["火花"], "技能解锁等级": ["1"], "血脉技能": [], "可学技能石": [],
        },
        "地地": {
            "主属性": "地面系", "2属性": "", "特性": "", "特性描述": "",
            "生命": 100, "物攻": 80, "魔攻": 70, "物防": 70, "魔防": 70, "速度": 50,
            "技能": ["拍击"], "技能解锁等级": ["1"], "血脉技能": [], "可学技能石": [],
        },
    }
    return skills, pets


def test_migrate_import_compile_catalog_and_battle(tmp_path: Path):
    conn = migrate(reset=True, db_path=tmp_path / "data.db")
    skills, pets = _sample_data()
    ability_lookup = import_abilities(conn, pets)
    skill_lookup = import_skills(conn, skills)
    import_pets(conn, pets, skill_lookup, ability_lookup)
    conn.commit()

    catalog = compile_catalog(conn)
    assert catalog.pets_by_name["地地"].types == ("地", "")
    assert catalog.skills_by_name["火花"].element == "火"
    assert catalog.skills_by_name["火花"].effects

    engine = BattleEngine(
        [catalog.build_pet("火火")],
        [catalog.build_pet("地地")],
    )
    engine.step(MoveDecision("move", skill_index=0), MoveDecision("move", skill_index=0))
    assert engine.state.turn_number == 1
    assert engine.state.log
    conn.close()


def test_import_rejects_legacy_structured_elements(tmp_path: Path):
    conn = migrate(reset=True, db_path=tmp_path / "data.db")
    with pytest.raises(ValueError):
        import_skills(conn, {
            "旧属性技能": {"技能名称": "旧属性技能", "属性": "钢", "技能类别": "物攻", "耗能": 1, "威力": 1, "效果": ""}
        })
    conn.close()


def test_core_pet_naming_guard():
    forbidden = ("Persistent" + "Pokemon", "Active" + "Pokemon", "Pokemon")
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
