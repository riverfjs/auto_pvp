"""Unit tests for type_chart.py — verified against WIKI 克制计算器."""

import pytest
from roco.engine.enums import Element
from roco.compiler.type_chart import (
    TYPES,
    CHART,
    STRONG_MULT,
    RESIST_MULT,
    WEAK_MULT,
    VULN_MULT,
    OVERLAP_WEAK_MULT,
    OVERLAP_VULN_MULT,
    effectiveness,
    effectiveness_v2,
    attacking_types,
    defending_types,
    coverage,
    status_immunity,
)


# ── data integrity ──────────────────────────────────────────────

def test_all_types_present():
    assert len(TYPES) == 18
    assert "无" not in TYPES
    assert "岩" not in TYPES
    assert "地" in TYPES
    assert all(t in CHART for t in TYPES)


def test_element_aliases_use_roco_ground_not_legacy_elements():
    assert not hasattr(Element, "ROCK")
    assert Element.from_str("地") is Element.GROUND
    for invalid in ("地面", "岩", "岩石", "钢", "Rock", "Steel"):
        with pytest.raises(ValueError):
            Element.from_str(invalid)


def test_every_type_has_four_facets():
    """Every type has strong, resist, weak, vulnerable keys."""
    for t in TYPES:
        for key in ("strong", "resist", "weak", "vulnerable"):
            assert key in CHART[t], f"{t} missing key '{key}'"
            assert isinstance(CHART[t][key], list), f"{t}.{key} should be a list"


def test_chart_symmetry():
    """If A is strong against B, then B should have A in weak or vulnerable."""
    for atk in TYPES:
        for dfn in CHART[atk]["strong"]:
            assert atk in CHART[dfn]["weak"], (
                f"{atk} strong vs {dfn} → {dfn}.weak should contain {atk}"
            )


# ── single-type effectiveness ───────────────────────────────────

@pytest.mark.parametrize("move,defender,expected", [
    # From chart: Fire strong vs Grass, Ice, Bug, Mech
    ("火", "草",   STRONG_MULT),
    ("火", "冰",   STRONG_MULT),
    ("火", "虫",   STRONG_MULT),
    ("火", "机械", STRONG_MULT),
    # Fire resist vs Water, Ground, Dragon
    ("火", "水",   RESIST_MULT),
    ("火", "地",   RESIST_MULT),
    ("火", "龙",   RESIST_MULT),
    # Neutral
    ("火", "普通", 1.0),
    ("火", "火",   1.0),
    ("火", "电",   1.0),
    # Ghost (幽) strong vs Light, Ghost, Illusion
    ("幽", "光",   STRONG_MULT),
    ("幽", "幽",   STRONG_MULT),
    ("幽", "幻",   STRONG_MULT),
    # Ghost resist vs Normal, Dark
    ("幽", "普通", RESIST_MULT),
    ("幽", "恶",   RESIST_MULT),
    # Normal hits nothing super effectively
    ("普通", "草", 1.0),
    ("普通", "火", 1.0),
])
def test_single_type_effectiveness(move, defender, expected):
    assert effectiveness(move, (defender,)) == expected


def test_single_type_all():
    """Verify every chart entry for self-consistency."""
    for move in TYPES:
        for dfn in TYPES:
            mult = effectiveness(move, (dfn,))
            if dfn in CHART[move]["strong"]:
                assert mult == STRONG_MULT, f"{move} → {dfn} should be {STRONG_MULT}, got {mult}"
            elif dfn in CHART[move]["resist"]:
                assert mult == RESIST_MULT, f"{move} → {dfn} should be {RESIST_MULT}, got {mult}"
            else:
                assert mult == 1.0, f"{move} → {dfn} should be 1.0, got {mult}"


# ── dual-type effectiveness ─────────────────────────────────────

def test_dual_type_overlap_weak():
    """草/冰 both weak to 火 → 3.0x"""
    # 草.weak = [火,冰,毒,虫,翼], 冰.weak = [火,地,武,机械]
    assert effectiveness_v2("火", ("草", "冰")) == OVERLAP_WEAK_MULT


def test_dual_type_overlap_vulnerable():
    """毒/虫 both vulnerable to 草 → 0.25x"""
    # 毒.vulnerable = [草,毒,虫,武,萌], 虫.vulnerable = [草,武]
    assert effectiveness_v2("草", ("毒", "虫")) == OVERLAP_VULN_MULT


def test_dual_type_cancel():
    """火 weak to 水, 草 vulnerable to 水 → cancel → 1.0"""
    # 火.weak = [水,地], 草.vulnerable = [水,地,电,光]
    # Water appears in both → canceled
    assert effectiveness_v2("水", ("火", "草")) == 1.0


def test_dual_type_single_weak():
    """Only one type weak → 2.0"""
    # 草.weak = [火,冰,毒,虫,翼], 毒 doesn't have 冰 in weak or vulnerable
    # 草 is weak to 冰, 毒 is neutral to 冰 → 2.0
    assert effectiveness_v2("冰", ("草", "毒")) == WEAK_MULT


def test_dual_type_single_vulnerable():
    """Only one type vulnerable → 0.5"""
    # 龙.vulnerable = [草,火,水,电,翼], 恶 doesn't have 火 in weak or vulnerable
    assert effectiveness_v2("火", ("龙", "恶")) == VULN_MULT


def test_dual_type_neutral():
    """Neither type affected → 1.0"""
    assert effectiveness_v2("普通", ("草", "火")) == 1.0


# ── famous dual-type combos ─────────────────────────────────────

@pytest.mark.parametrize("move,defenders,expected", [
    # 水+地 → 草 hits 3.0 (both weak to 草)
    ("草", ("水", "地"), OVERLAP_WEAK_MULT),
    # 火+草 → 水 cancels (火 weak, 草 vulnerable)
    ("水", ("火", "草"), 1.0),
    # 龙+翼 → 冰 3.0 (both weak to 冰)
    ("冰", ("龙", "翼"), OVERLAP_WEAK_MULT),
    # 毒+虫 → 地 cancels (毒 weak, 虫 neutral)
    # Actually: 毒.weak=[地,恶,幻], 虫 has nothing for 地 → 2.0
    ("地", ("毒", "虫"), WEAK_MULT),
    # 机械+地 dual type
    # 机械.vulnerable=[普通,草,冰,龙,毒,虫,翼,萌,机械,幻], 地.vulnerable=[普通,火,电,毒,翼]
    # 普通 → both vulnerable → 0.25
    ("普通", ("机械", "地"), OVERLAP_VULN_MULT),
])
def test_known_dual_combos(move, defenders, expected):
    assert effectiveness_v2(move, defenders) == expected


# ── edge cases ──────────────────────────────────────────────────

def test_invalid_move_type():
    assert effectiveness("不存在", ("火",)) == 1.0


def test_no_defender():
    assert effectiveness("火", ()) == 1.0
    assert effectiveness("火", ("无",)) == 1.0


def test_invalid_defender_ignored():
    assert effectiveness("火", ("草", "不存在")) == STRONG_MULT


# ── attacking_types / defending_types ───────────────────────────

def test_attacking_types_fire():
    result = attacking_types("火")
    assert set(result["2.0"]) == {"草", "冰", "虫", "机械"}
    assert set(result["0.5"]) == {"水", "地", "龙"}


def test_defending_types_water():
    result = defending_types("水")
    # Water weak to: 草, 电
    assert set(result["2.0"]) == {"草", "电"}
    # Water vulnerable to: 火, 机械
    assert set(result["0.5"]) == {"火", "机械"}


# ── coverage ────────────────────────────────────────────────────

def test_coverage_single_type():
    """Fire covers Grass, Ice, Bug, Mech → 4 SE types."""
    cov = coverage(["火"])
    assert set(cov["super_effective"]) == {"草", "冰", "虫", "机械"}
    assert "水" in cov["missing"]  # resisted


def test_coverage_boltbeam():
    """Electric + Ice (classic boltbeam combo)."""
    cov = coverage(["电", "冰"])
    # Electric SE: 水, 翼
    # Ice SE: 草, 地, 龙, 翼
    combined = {"水", "翼", "草", "地", "龙"}
    assert set(cov["super_effective"]) == combined


def test_coverage_fire_water_grass():
    """Fire/Water/Grass core — covers many types."""
    cov = coverage(["火", "水", "草"])
    # Fire SE: 草,冰,虫,机械; Water SE: 火,地,机械; Grass SE: 水,光,地
    se = set(cov["super_effective"])
    assert "草" in se or "冰" in se  # at least some fire coverage
    assert len(se) >= 3


def test_coverage_empty():
    cov = coverage([])
    assert cov["super_effective"] == []
    assert len(cov["missing"]) == 18


# ── status immunity ─────────────────────────────────────────────

def test_status_immunity_fire():
    imm = status_immunity(("火",))
    assert imm["灼烧"] is True
    assert imm["寄生"] is False


def test_status_immunity_dual():
    imm = status_immunity(("火", "草"))
    assert imm["灼烧"] is True
    assert imm["寄生"] is True
    assert imm["中毒"] is False


def test_status_immunity_none():
    imm = status_immunity(("普通",))
    assert all(v is False for v in imm.values())


# ── WIKI calculator edge cases ──────────────────────────────────

def test_机械_defensive_profile():
    """机械 has the most resistances."""
    # 机械.vulnerable has 10 types
    assert len(CHART["机械"]["vulnerable"]) == 10
    # 机械.weak has only 3 types
    assert len(CHART["机械"]["weak"]) == 3


def test_普通_has_no_strong():
    assert CHART["普通"]["strong"] == []
    # All matchups should be neutral or resisted
    for t in TYPES:
        mult = effectiveness("普通", (t,))
        assert mult in (1.0, 0.5), f"普通 vs {t} = {mult}"
