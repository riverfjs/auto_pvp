"""Tests for import-time skill classification into compiled effects."""

from roco.data.effect_classifier import refresh_ability_classification, refresh_skill_classification
from roco.compiler.effect_compile import compile_skill_effects
from roco.compiler.effect_model import EffectFlag, EffectTag, Timing
from roco.engine.enums import SkillCategory
from roco.compiler.skill_tags import classify
from roco.compiler.records import SkillData


def _compiled(effect: str, name: str = "test", element: str = "普通",
              category: str | SkillCategory = "物攻", power: int = 50):
    skill = SkillData(name=name, element=element, category=category,
                      energy=1, power=power, effect=effect)
    classify(skill)
    rows = compile_skill_effects(0, skill)
    return skill, rows


def _effect(rows, tag: EffectTag):
    return next(row.effect for row in rows if row.effect.tag is tag)


def test_life_drain():
    _, rows = _compiled("造成物伤，吸血50%")
    assert _effect(rows, EffectTag.LIFE_DRAIN).params["pct"] == 0.5


def test_self_heal_hp():
    _, rows = _compiled("回复60%生命", power=0)
    assert _effect(rows, EffectTag.HEAL_HP).params["pct"] == 0.6


def test_self_heal_energy():
    _, rows = _compiled("回复4能量", power=0)
    assert _effect(rows, EffectTag.HEAL_ENERGY).params["amount"] == 4


def test_steal_energy():
    _, rows = _compiled("偷取3能量", power=0)
    assert _effect(rows, EffectTag.STEAL_ENERGY).params["amount"] == 3


def test_damage_reduction():
    _, rows = _compiled("减伤70%", power=0, category="防御")
    assert _effect(rows, EffectTag.DAMAGE_REDUCTION).params["pct"] == 0.7


def test_hit_count():
    sk, rows = _compiled("连击3次")
    assert sk.hit_count == 3
    assert _effect(rows, EffectTag.DAMAGE).params["hit_count"] == 3


def test_priority():
    sk, _ = _compiled("先制+1")
    assert sk.priority_mod == 1


def test_force_switch():
    _, rows = _compiled("造成物伤后折返")
    assert _effect(rows, EffectTag.FORCE_SWITCH).timing is Timing.AFTER_MOVE


def test_burn_stacks():
    _, rows = _compiled("造成3层灼烧")
    assert _effect(rows, EffectTag.BURN).params["stacks"] == 3


def test_poison_stacks():
    _, rows = _compiled("施加2层中毒", power=0)
    assert _effect(rows, EffectTag.POISON).params["stacks"] == 2


def test_self_atk_up():
    _, rows = _compiled("物攻+30%", power=0)
    assert _effect(rows, EffectTag.SELF_BUFF).params["atk"] == 0.3


def test_self_atk_down():
    _, rows = _compiled("物攻-20%", power=0)
    assert _effect(rows, EffectTag.SELF_BUFF).params["atk"] == -0.2


def test_enemy_def_down():
    _, rows = _compiled("敌方物防-40%", power=0)
    assert _effect(rows, EffectTag.ENEMY_DEBUFF).params["def"] == 0.4


def test_combined_effects():
    _, rows = _compiled("造成物伤，吸血50%，回复20%生命，偷取2能量")
    assert _effect(rows, EffectTag.LIFE_DRAIN).params["pct"] == 0.5
    assert _effect(rows, EffectTag.HEAL_HP).params["pct"] == 0.2
    assert _effect(rows, EffectTag.STEAL_ENERGY).params["amount"] == 2


def test_steal_energy_amount():
    _, rows = _compiled("偷取5能量", power=0)
    assert _effect(rows, EffectTag.STEAL_ENERGY).params["amount"] == 5


def test_empty():
    sk, rows = _compiled("", power=0)
    assert sk.effect_flags == EffectFlag.NONE
    assert rows == ()


def test_burn_keyword():
    _, rows = _compiled("造成灼烧", power=0)
    assert _effect(rows, EffectTag.BURN).params["stacks"] == 1


def test_classify_preserves_name():
    sk, rows = _compiled("造成魔伤，2层灼烧", name="火球", element="火", category="魔攻")
    assert sk.name == "火球"
    assert _effect(rows, EffectTag.BURN).params["stacks"] == 2


def test_pure_damage_tag():
    sk, rows = _compiled("对敌方精灵造成物理伤害", name="撞击")
    assert sk.effect_flags & EffectFlag.PURE_DAMAGE
    assert _effect(rows, EffectTag.DAMAGE)


def test_weather_type():
    _, rows = _compiled("沙涌", power=0)
    assert _effect(rows, EffectTag.WEATHER).params["type"] == "sandstorm"


def test_weather_rain():
    _, rows = _compiled("祈雨", power=0)
    assert _effect(rows, EffectTag.WEATHER).params["type"] == "rain"


def test_weather_snow():
    _, rows = _compiled("雪天", power=0)
    assert _effect(rows, EffectTag.WEATHER).params["type"] == "snow"


def test_enemy_cost_up():
    _, rows = _compiled("全技能能耗+3", power=0)
    assert _effect(rows, EffectTag.ENEMY_ENERGY_COST_UP).params["amount"] == 3


def test_hp_for_energy():
    _, rows = _compiled("失去10%生命", power=0)
    assert _effect(rows, EffectTag.HP_FOR_ENERGY).params["pct"] == 0.1


def test_permanent_hit_growth():
    _, rows = _compiled("连击数永久+2")
    assert _effect(rows, EffectTag.PERMANENT_MOD).params == {"target": "hit_count", "delta": 2}


def test_permanent_power_growth():
    _, rows = _compiled("威力永久+10")
    assert _effect(rows, EffectTag.PERMANENT_MOD).params == {"target": "power", "delta": 10}


def test_counter_tag():
    sk, _ = _compiled("造成物伤，应对状态：本次技能威力翻倍")
    assert sk.effect_flags & EffectFlag.COUNTER


def test_generated_mark_primitives_are_concrete():
    record = refresh_skill_classification({
        "kind": "skill",
        "name": "打湿",
        "element": "水",
        "category": "状态",
        "energy": 1,
        "power": 0,
        "effect_text": "自己获得1层湿润印记。",
    })

    assert any(effect["tag"] == "MOISTURE_MARK" for effect in record["effects"])
    assert all(effect["tag"] != "MARK" for effect in record["effects"])


def test_mark_dispel_operation_is_concrete():
    record = refresh_skill_classification({
        "kind": "skill",
        "name": "倾泻",
        "element": "水",
        "category": "魔攻",
        "energy": 2,
        "power": 65,
        "effect_text": "造成魔伤，未被防御时驱散双方所有印记。",
    })

    assert any(effect["tag"] == "DISPEL_MARKS" for effect in record["effects"])


def test_canonical_skill_manual_rules_extend_generated_effects():
    record = refresh_skill_classification({
        "kind": "skill",
        "name": "伺机而动",
        "element": "普通",
        "category": "状态",
        "energy": 1,
        "power": 0,
        "effect_text": "",
    })

    assert record["classification"]["source"] == "manual:skill:extend"
    assert any(effect["tag"] == "NEXT_ATTACK_MOD" for effect in record["effects"])


def test_canonical_ability_missing_effect_is_explicit_gap():
    record = refresh_ability_classification({
        "kind": "ability",
        "name": "未分类特性",
        "description": "这条描述还没有安全分类规则",
    })

    assert record["classification"]["status"] == "needs_manual"
    assert record["classification"]["gaps"][0]["reason"] == "structured_effect_missing"
