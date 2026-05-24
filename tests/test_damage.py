"""Unit tests for damage.py — stat computation & damage formulas."""

import pytest
from roco.data.scalar_damage import (
    compute_stats,
    apply_iv_mod,
    apply_nature_mod,
    calc_attack_damage,
    calc_burn_damage,
    calc_burn_decay,
    calc_poison_damage,
    get_type_multiplier,
    can_use_skill,
    calc_energy_after_gain,
    calc_energy_after_use,
    buff_multiplier,
    clamp_stage,
    apply_buff_stages,
)
from roco.common.natures import NATURE_MOD, NATURE_NAME_TO_ID, PLAYER_NATURE_IDS


# ── Stat computation ───────────────────────────────────────────

def test_compute_stats_no_mods():
    stats = compute_stats(100, 80, 70, 90, 85, 60)
    assert stats == {"hp": 100, "atk_phys": 80, "atk_mag": 70,
                     "def_phys": 90, "def_mag": 85, "speed": 60}


def test_compute_stats_iv_only():
    stats = compute_stats(100, 80, 70, 90, 85, 60, ivs=["物攻", "速度"])
    assert stats["hp"] == 100
    assert stats["atk_phys"] == 88   # 80 * 1.1 = 88
    assert stats["atk_mag"] == 70
    assert stats["speed"] == 66       # 60 * 1.1 = 66


def test_compute_stats_nature_only_adamant():
    stats = compute_stats(100, 80, 70, 90, 85, 60, nature="固执")
    assert stats["atk_phys"] == 88   # 80 * 1.1
    assert stats["atk_mag"] == 63    # 70 * 0.9
    assert stats["speed"] == 60      # unchanged


def test_compute_stats_nature_and_iv():
    stats = compute_stats(100, 80, 70, 90, 85, 60, nature="固执", ivs=["物攻"])
    # IV first: 80 * 1.1 = 88, then nature: 88 * 1.1 = 96
    assert stats["atk_phys"] == 96
    assert stats["atk_mag"] == 63   # 70 * 0.9 = 63


def test_compute_stats_floor_rounding():
    stats = compute_stats(100, 79, 70, 90, 85, 60, ivs=["物攻"])
    assert stats["atk_phys"] == 86   # 79 * 1.1 = 86.9 → 86


def test_compute_stats_unknown_nature():
    stats = compute_stats(100, 80, 70, 90, 85, 60, nature="不存在")
    assert stats["atk_phys"] == 80
    assert stats["atk_mag"] == 70


def test_compute_stats_pak_hp_nature():
    stats = compute_stats(100, 80, 70, 90, 85, 60, nature="沉默")
    assert stats["hp"] == 110
    assert stats["atk_phys"] == 72


def test_apply_iv_mod_keeps_hp_unchanged():
    """HP IV leaves HP unchanged; only non-HP stats get IV bonus."""
    stats = apply_iv_mod({"hp": 200, "atk_phys": 80, "atk_mag": 70,
                          "def_phys": 90, "def_mag": 85, "speed": 60},
                         ["生命", "物攻"])
    assert stats["hp"] == 200       # HP should NOT change
    assert stats["atk_phys"] == 88


# ── Nature mapping integrity ───────────────────────────────────

def test_all_natures_in_config():
    """Verify pak player natures are generated, not the old hand table."""
    assert len(PLAYER_NATURE_IDS) == 30
    assert len(NATURE_MOD) == 30
    assert NATURE_NAME_TO_ID["固执"] == 2
    assert NATURE_MOD["逞强"] == ("atk_phys", "hp")
    assert "保守" not in NATURE_MOD


def test_nature_pairs_are_distinct():
    """No nature boosts and reduces the same stat."""
    for name, (boost, reduce) in NATURE_MOD.items():
        if boost and reduce:
            assert boost != reduce, f"{name} boosts and reduces {boost}"


# ── Damage formulas ────────────────────────────────────────────

@pytest.mark.parametrize("power,atk,def_,mult,expected", [
    (100, 120, 100, 1.0, 108),   # 100*120/100 * 1.0 * 0.9 = 108
    (100, 120, 100, 2.0, 216),
    (100, 120, 100, 0.5, 54),
    (100, 120, 100, 3.0, 324),
    (100, 100, 200, 1.0, 45),    # 100*100/200 * 1.0 * 0.9 = 45
    (100, 100, 200, 2.0, 90),
])
def test_calc_attack_damage(power, atk, def_, mult, expected):
    assert calc_attack_damage(power, atk, def_, mult) == expected


def test_calc_attack_damage_min_one():
    """Even resisted, non-zero power → min damage 1."""
    assert calc_attack_damage(10, 100, 200, 0.25) == 1


def test_calc_attack_damage_zero_power():
    """Zero power → 0 damage (status/defensive move)."""
    assert calc_attack_damage(0, 100, 100, 1.0) == 0


def test_calc_attack_damage_floor():
    """Damage floors to int with 0.9 constant."""
    dmg = calc_attack_damage(95, 87, 113, 1.0)
    assert dmg == int(95 * 87 / 113 * 0.9)


# ── Burn damage ────────────────────────────────────────────────

def test_burn_damage_basic():
    """100 HP, 10 stacks, 2% = 20 damage."""
    assert calc_burn_damage(100, 10) == 20


def test_burn_damage_cap():
    """5000 HP capped at 1000, 30 stacks = 1000*30*0.02 = 600."""
    assert calc_burn_damage(5000, 30) == 600


def test_burn_damage_mid_turn_ignores_type():
    """Mid-turn burn: type_mult forced to 1.0."""
    dmg = calc_burn_damage(1000, 10, type_mult=2.0, mid_turn=True)
    assert dmg == 200  # 1000 * 10 * 0.02 * 1.0


def test_burn_damage_end_turn_respects_type():
    """End-turn burn applies type multiplier."""
    dmg = calc_burn_damage(1000, 10, type_mult=2.0, mid_turn=False)
    assert dmg == 400  # 1000 * 10 * 0.02 * 2.0


def test_burn_damage_zero_stacks():
    assert calc_burn_damage(1000, 0) == 0


def test_burn_decay():
    assert calc_burn_decay(10) == 5
    assert calc_burn_decay(9) == 5   # ceil(9/2) = 5
    assert calc_burn_decay(1) == 0


# ── Poison damage ──────────────────────────────────────────────

def test_poison_damage():
    assert calc_poison_damage(400, 1) == 12   # 400 * 1 * 0.03 = 12
    assert calc_poison_damage(400, 3) == 36   # 400 * 3 * 0.03 = 36


def test_poison_zero_stacks():
    assert calc_poison_damage(400, 0) == 0


# ── Type multiplier ────────────────────────────────────────────

def test_get_type_multiplier_super_effective():
    assert get_type_multiplier("火", ("草",)) == 2.0


def test_get_type_multiplier_resisted():
    assert get_type_multiplier("火", ("水",)) == 0.5


def test_get_type_multiplier_neutral():
    assert get_type_multiplier("火", ("普通",)) == 1.0


def test_get_type_multiplier_dual_overlap_weak():
    # 火 vs 草+冰 — both weak to fire → 3.0
    assert get_type_multiplier("火", ("草", "冰")) == 3.0


def test_get_type_multiplier_dual_cancel():
    # 水 vs 火+草 — fire weak to water, grass vulnerable to water → cancel → 1.0
    assert get_type_multiplier("水", ("火", "草")) == 1.0


def test_get_type_multiplier_dual_vulnerable_overlap():
    # 普通 vs 机械+地 — both resist 普通.  Pak's ``double_restrained_percent``
    # (7500 BPS) is the source of truth here, so the multiplier is 0.75×,
    # not the legacy hand-coded 0.25× / 0.333× from the BWiki chart.
    assert get_type_multiplier("普通", ("机械", "地")) == 0.75


# ── Energy ─────────────────────────────────────────────────────

def test_can_use_skill_yes():
    assert can_use_skill(5, 3) is True


def test_can_use_skill_exact():
    assert can_use_skill(3, 3) is True


def test_can_use_skill_no():
    assert can_use_skill(2, 3) is False


def test_energy_gain():
    assert calc_energy_after_gain(3) == 8


def test_energy_gain_capped():
    assert calc_energy_after_gain(9) == 10  # capped at MAX_ENERGY=10


def test_energy_after_use():
    assert calc_energy_after_use(5, 3) == 2


def test_energy_after_use_floor_zero():
    assert calc_energy_after_use(1, 3) == 0


# ── Buff stages ────────────────────────────────────────────────

def test_buff_multiplier_positive():
    assert buff_multiplier(0) == 1.0
    assert buff_multiplier(1) == 1.1
    assert buff_multiplier(6) == 1.6


def test_buff_multiplier_negative():
    assert buff_multiplier(-1) == pytest.approx(0.909, rel=0.01)
    assert buff_multiplier(-6) == pytest.approx(0.625, rel=0.01)


def test_clamp_stage():
    assert clamp_stage(0) == 0
    assert clamp_stage(6) == 6
    assert clamp_stage(10) == 6
    assert clamp_stage(-6) == -6
    assert clamp_stage(-10) == -6


def test_apply_buff_stages():
    stats = {"hp": 100, "atk_phys": 80, "atk_mag": 70,
             "def_phys": 90, "def_mag": 85, "speed": 60}
    result = apply_buff_stages(stats, {"atk_phys": 2, "speed": -1})
    assert result["hp"] == 100                          # HP never buffed
    assert result["atk_phys"] == int(80 * 1.2)          # +2 → 1.2x
    assert result["speed"] == int(60 * buff_multiplier(-1))  # -1 → ~0.909x
    assert result["atk_mag"] == 70                      # unbuffed


def test_apply_buff_stages_hp_unaffected():
    stats = {"hp": 100, "atk_phys": 80, "atk_mag": 70,
             "def_phys": 90, "def_mag": 85, "speed": 60}
    result = apply_buff_stages(stats, {"hp": 5})
    assert result["hp"] == 100  # HP ignores buff stages
