"""Tests for skill effect parsing and execution."""

from roco.systems.effects import parse_effect_text, apply_effects_to_skill
from roco.engine.state import SkillRef


# ── Effect text parsing ────────────────────────────────────────

def test_parse_life_drain():
    r = parse_effect_text("造成物伤，吸血50%")
    assert r["life_drain"] == 0.5


def test_parse_self_heal_hp():
    r = parse_effect_text("回复60%生命")
    assert r["self_heal_hp"] == 0.6


def test_parse_self_heal_energy():
    r = parse_effect_text("回复4能量")
    assert r["self_heal_energy"] == 4


def test_parse_steal_energy():
    r = parse_effect_text("偷取3能量")
    assert r["steal_energy"] == 3


def test_parse_damage_reduction():
    r = parse_effect_text("减伤70%")
    assert r["damage_reduction"] == 0.7


def test_parse_hit_count():
    r = parse_effect_text("连击3次")
    assert r["hit_count"] == 3


def test_parse_priority():
    r = parse_effect_text("先制+1")
    assert r["priority_mod"] == 1


def test_parse_force_switch():
    r = parse_effect_text("造成物伤后折返")
    assert r["force_switch"] is True


def test_parse_burn_stacks():
    r = parse_effect_text("造成3层灼烧")
    assert r["burn_stacks"] == 3


def test_parse_poison_stacks():
    r = parse_effect_text("施加2层中毒")
    assert r["poison_stacks"] == 2


def test_parse_self_atk_up():
    r = parse_effect_text("物攻+30%")
    assert r["self_atk"] == 0.3


def test_parse_self_atk_down():
    r = parse_effect_text("物攻-20%")
    assert r["self_atk"] == -0.2


def test_parse_enemy_def_down():
    r = parse_effect_text("敌方物防-40%")
    assert r["enemy_def"] == 0.4


def test_parse_combined_effects():
    r = parse_effect_text("造成物伤，吸血50%，回复20%HP，偷取2能量")
    assert r["life_drain"] == 0.5
    assert r["self_heal_hp"] == 0.2
    assert r["steal_energy"] == 2


def test_parse_empty():
    assert parse_effect_text("") == {}


def test_parse_burn_keyword_fallback():
    r = parse_effect_text("造成灼烧")
    assert r["burn_stacks"] == 1


# ── Apply to SkillRef ──────────────────────────────────────────

def test_apply_effects_to_skill():
    sk = SkillRef(name="吸血斩", element="恶", category="物攻", energy=3, power=90,
                  effect="造成物伤，吸血50%")
    apply_effects_to_skill(sk)
    assert sk.life_drain == 0.5


def test_apply_effects_does_not_change_name():
    sk = SkillRef(name="火球", element="火", category="魔攻", energy=2, power=60,
                  effect="造成魔伤，2层灼烧")
    apply_effects_to_skill(sk)
    assert sk.name == "火球"
    assert sk.burn_stacks == 2
