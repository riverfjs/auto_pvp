"""Tests for the pak-derived type effectiveness chart.

The hand-written ``roco.compiler_v2.type_chart`` BWiki-reverse-engineered
table has been retired; the canonical chart now lives in
``roco.generated.type_chart`` (regenerated from pak ``TYPE_DICTIONARY``
by :mod:`roco.compiler_v2.gen_prefix_map`).  These tests probe the
generated table directly so any drift between pak and our compiled
artifacts surfaces.
"""

import pytest

from roco.common.constants import (
    BPS,
    TYPE_DOUBLE_RESIST_BPS,
    TYPE_DOUBLE_WEAK_BPS,
    TYPE_NEUTRAL_BPS,
    TYPE_RESIST_BPS,
    TYPE_WEAK_BPS,
)
from roco.common.enums import ELEMENT_NAMES, Element
from roco.compiler_v2.scalar_damage import _effectiveness_bps, get_type_multiplier
from roco.generated.type_chart import TYPE_CHART_BPS


def _eid(name: str) -> int:
    return Element.from_str(name).value


# ── chart shape ────────────────────────────────────────────────────

def test_chart_shape_matches_elements():
    n = len(ELEMENT_NAMES)
    assert len(TYPE_CHART_BPS) == n
    for row in TYPE_CHART_BPS:
        assert len(row) == n


def test_chart_entries_are_one_of_three_canonical_values():
    """pak produces only ``±1`` / missing → 2.0× / 0.5× / 1.0× BPS values."""
    allowed = {TYPE_NEUTRAL_BPS, TYPE_WEAK_BPS, TYPE_RESIST_BPS}
    for row in TYPE_CHART_BPS:
        for value in row:
            assert value in allowed


# ── single-defender pak spot-checks ─────────────────────────────────

@pytest.mark.parametrize("attacker, defender, expected", [
    ("火", "草", TYPE_WEAK_BPS),    # fire 2× grass
    ("火", "水", TYPE_RESIST_BPS),  # fire 0.5× water
    ("火", "火", TYPE_NEUTRAL_BPS),
    ("水", "火", TYPE_WEAK_BPS),
    ("草", "水", TYPE_WEAK_BPS),
    ("草", "火", TYPE_RESIST_BPS),
    ("电", "翼", TYPE_WEAK_BPS),
    ("电", "地", TYPE_RESIST_BPS),
    ("普通", "幽", TYPE_RESIST_BPS),
])
def test_single_defender_bps(attacker, defender, expected):
    assert TYPE_CHART_BPS[_eid(attacker)][_eid(defender)] == expected


# ── dual-type composition (compiler/kernel share this rule) ─────────

def test_both_weak_overlap_uses_pak_triple():
    # 火 vs 草/冰 — both defenders weak to 火.
    assert _effectiveness_bps("火", ("草", "冰")) == TYPE_DOUBLE_WEAK_BPS


def test_both_resist_overlap_uses_pak_double_restrained():
    # 草 vs 毒/虫 — both defenders resist 草.
    # (毒 prefix 12: type_restraint3=-1, 虫 prefix 13: type_restraint3=-1)
    assert _effectiveness_bps("草", ("毒", "虫")) == TYPE_DOUBLE_RESIST_BPS


def test_one_weak_one_resist_cancels_to_neutral():
    # 水 vs 火/草 — fire weak to water, grass resists water.
    assert _effectiveness_bps("水", ("火", "草")) == TYPE_NEUTRAL_BPS


def test_single_weak_partner_neutral_keeps_weak():
    # 冰 vs 草/毒 — grass weak to ice, poison neutral to ice.
    assert _effectiveness_bps("冰", ("草", "毒")) == TYPE_WEAK_BPS


def test_missing_defender_means_neutral():
    assert _effectiveness_bps("火", ()) == TYPE_NEUTRAL_BPS
    assert _effectiveness_bps("火", ("无",)) == TYPE_NEUTRAL_BPS


def test_unknown_attacker_falls_back_to_neutral():
    assert _effectiveness_bps("不存在", ("火",)) == TYPE_NEUTRAL_BPS


# ── float API used by scalar_damage callers ─────────────────────────

@pytest.mark.parametrize("attacker, defender, expected", [
    ("火", ("草",),       TYPE_WEAK_BPS / BPS),
    ("火", ("水",),       TYPE_RESIST_BPS / BPS),
    ("草", ("水", "地"),  TYPE_DOUBLE_WEAK_BPS / BPS),
    ("草", ("毒", "虫"),  TYPE_DOUBLE_RESIST_BPS / BPS),
    ("水", ("火", "草"),  TYPE_NEUTRAL_BPS / BPS),
])
def test_get_type_multiplier_matches_bps(attacker, defender, expected):
    assert get_type_multiplier(attacker, defender) == expected
