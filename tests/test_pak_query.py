from roco.data.parse_pak import DEFAULT_PAK_DATA_DIR
from roco.pak_query import cli
from roco.pak_query.index import PakLookup


def _lookup() -> PakLookup:
    if not (DEFAULT_PAK_DATA_DIR / "BinData" / "LEVEL_SKILL_CONF.json").exists():
        raise AssertionError("pak data not extracted")
    return PakLookup(DEFAULT_PAK_DATA_DIR)


def test_pet_query_uses_level_skill_conf_for_evolved_bloodline_skills():
    lookup = _lookup()
    reports = lookup.pet_report("音速犬")
    assert len(reports) == 1
    fire_bloodline = [
        link for link in reports[0]["bloodline_skills"]
        if link.skill_id == 7040370 and link.bloodline == "火"
    ]
    assert fire_bloodline


def test_skill_query_lists_pets_that_learn_bloodline_skill():
    lookup = _lookup()
    reports = lookup.skill_report("火焰箭")
    learner_ids = {
        link.pet_id
        for report in reports
        for link in report["learners"]
        if link.skill_id == 7040370 and link.source_type == "bloodline"
    }
    assert {3070, 3071}.issubset(learner_ids)


def test_skill_stone_query_includes_item_and_handbook_unlock_conditions():
    lookup = _lookup()
    reports = lookup.skill_report("毒沼")
    assert reports and reports[0]["skill"].id == 7120200
    sources = reports[0]["item_sources"]
    assert any(source.item_name == "毒沼" for source in sources)
    handbook_topics = [
        topic
        for source in sources
        for topic in source.handbook
    ]
    assert any(topic.get("handbook_pet") == "月亮砣" for topic in handbook_topics)
    assert any("使用1次毒沼" in topic.get("topic_desc", "") for topic in handbook_topics)


def test_skill_cli_prints_shared_stone_conditions_once(capsys):
    rc = cli.main(["skill", "伺机而动"])
    assert rc == 0
    out = capsys.readouterr().out
    assert out.count("获取: 炼金造物获得") == 1
    assert out.count("获取: 完成鸭吉吉的图鉴课题获得") == 1
    assert out.count("图鉴: 鸭吉吉 - 使用1次伺机而动") == 1
    assert "冬羽雀 (3028) | 技能石技能\n    伺机而动" not in out
    assert "冬羽雀 (3028) | 技能石技能" in out


def test_ability_query_lists_owning_pets():
    lookup = _lookup()
    reports = lookup.ability_report("专注力")
    owner_ids = {
        owner.pet_id
        for report in reports
        for owner in report["owners"]
    }
    assert {3070, 3071}.issubset(owner_ids)
