"""Tests for skill classification (pre-parse via classify())."""

from roco.engine.skill_tags import classify
from roco.engine.state import SkillRef


def _clsfy(effect: str, name: str = "test", element: str = "普通",
           category: str = "物攻") -> SkillRef:
    sk = SkillRef(name=name, element=element, category=category,
                  energy=1, power=50, effect=effect)
    return classify(sk)


def test_life_drain():
    sk = _clsfy("造成物伤，吸血50%")
    assert sk.life_drain == 0.5
    assert "drain" in sk.tags


def test_self_heal_hp():
    sk = _clsfy("回复60%生命")
    assert sk.self_heal_hp == 0.6
    assert "heal_hp" in sk.tags


def test_self_heal_energy():
    sk = _clsfy("回复4能量")
    assert sk.self_heal_energy == 4


def test_steal_energy():
    sk = _clsfy("偷取3能量")
    assert sk.steal_energy == 3


def test_damage_reduction():
    sk = _clsfy("减伤70%")
    assert sk.damage_reduction == 0.7
    assert "defense" in sk.tags


def test_hit_count():
    sk = _clsfy("连击3次")
    assert sk.hit_count == 3


def test_priority():
    sk = _clsfy("先制+1")
    assert sk.priority_mod == 1


def test_force_switch():
    sk = _clsfy("造成物伤后折返")
    assert sk.force_switch is True


def test_burn_stacks():
    sk = _clsfy("造成3层灼烧")
    assert sk.burn_stacks == 3


def test_poison_stacks():
    sk = _clsfy("施加2层中毒")
    assert sk.poison_stacks == 2


def test_self_atk_up():
    sk = _clsfy("物攻+30%")
    assert sk.self_atk == 0.3


def test_self_atk_down():
    sk = _clsfy("物攻-20%")
    assert sk.self_atk == -0.2


def test_enemy_def_down():
    sk = _clsfy("敌方物防-40%")
    assert sk.enemy_def == 0.4


def test_combined_effects():
    sk = _clsfy("造成物伤，吸血50%，回复20%HP，偷取2能量")
    assert sk.life_drain == 0.5
    assert sk.self_heal_hp == 0.2
    assert sk.steal_energy == 2


def test_steal_energy_amount():
    sk = _clsfy("偷取5能量")
    assert sk.steal_energy == 5


def test_empty():
    sk = _clsfy("")
    assert sk.tags == ["pure_damage"] or sk.tags == []


def test_burn_keyword():
    sk = _clsfy("造成灼烧")
    assert sk.burn_stacks >= 1


def test_classify_preserves_name():
    sk = _clsfy("造成魔伤，2层灼烧", name="火球", element="火", category="魔攻")
    assert sk.name == "火球"
    assert sk.burn_stacks == 2


def test_pure_damage_tag():
    sk = _clsfy("对敌方精灵造成物理伤害", name="撞击")
    assert "pure_damage" in sk.tags


def test_weather_type():
    sk = _clsfy("沙涌")
    assert sk.weather_type == "sandstorm"
    assert "weather" in sk.tags


def test_weather_rain():
    sk = _clsfy("祈雨")
    assert sk.weather_type == "rain"


def test_weather_snow():
    sk = _clsfy("雪天")
    assert sk.weather_type == "snow"


def test_enemy_cost_up():
    sk = _clsfy("全技能能耗+3")
    assert sk.enemy_cost_up_amount == 3


def test_hp_for_energy():
    sk = _clsfy("失去10%生命")
    assert sk.hp_cost_pct == 0.1


def test_permanent_hit_growth():
    sk = _clsfy("连击数永久+2")
    assert sk.permanent_hit_growth == 2


def test_permanent_power_growth():
    sk = _clsfy("威力永久+10")
    assert sk.permanent_power_growth == 10


def test_counter_tag():
    sk = _clsfy("造成物伤，应对状态：本次技能威力翻倍")
    assert "counter" in sk.tags
