"""Tests for the pak-axis family decoder module.

The family-axis decoder replaces hand-written exact effect rows when pak's
``effect_order/type/param`` shape is enough to derive the primitive.
The ``effect_order=31`` counter family was the first axis to land here,
replacing 76 hand-written ``P_INSTALL_COUNTER`` rules in
the historical exact-effect table.  These tests pin the migration contract:

* The decoder fires for every ``effect_order=31`` record in pak —
  not just the 76 previously-covered ids.
* The emitted row matches the exact-rule shape it replaces
  (``handler=P_INSTALL_COUNTER``, ``p0=response_skill_id``, timing
    override = ``battle_event:BEVT_BEFORE_HURT``).
* The pre-migration ack file does not regress: counter effect_ids that
  were *not* in the historical exact-effect table previously surfaced as gaps
  (type=2 emitted spurious H_DAMAGE rows or type=3 went to gap) — the
  new decoder covers them silently.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from roco.common.primitive_keys import (
    effect_order_key,
    effect_order_variant_key,
)
from roco.compiler_v2.effect_codegen import family_axes
from roco.compiler_v2.effect_codegen.family_axes import (
    COUNTER_INSTALL_TIMING,
    ET_BUFF_CONVERT,
    ET_COPY_BUFF,
    ET_COUNTER,
    ET_PURIFY,
    decode_family_axes,
)
from roco.compiler_v2.effect_codegen.outcomes import EmitOutcome
from roco.compiler_v2.effect_codegen.pak import PakTables
from roco.compiler_v2.timing_keys import pak_battle_event_key

P_DISPEL_DEBUFFS = effect_order_key("ET_PURIFY")
P_DISPEL_MARKS = effect_order_variant_key("ET_BUFF_CONVERT", "dispel_marks")
P_DISPEL_MARKS_TO_BURN = effect_order_variant_key("ET_BUFF_CONVERT", "dispel_marks_to_burn")
P_ENTRY_SELF_BUFF_BY_SOURCE_COUNT = effect_order_variant_key(
    "ET_HERO",
    "entry_self_buff_by_source_count",
)
P_EXCHANGE_HP_RATIO = effect_order_variant_key("ET_SWAP_STAT", "hp_ratio")
P_EXCHANGE_MOVES = effect_order_key("ET_SWAP_SKILLS")
P_HEAL_ENERGY = effect_order_key("ET_CHANGE_ENERGY")
P_HEAL_HP = effect_order_key("ET_RECOVER")
P_HIT_COUNT_DELTA = effect_order_key("ET_MULTIPLE")
P_INSTALL_COUNTER = effect_order_key("ET_COUNTER")
P_LIFE_DRAIN = effect_order_key("ET_SUCKBLOOD")
P_MIRROR_ENEMY_BUFFS = effect_order_key("ET_COPY_BUFF")
P_PRIORITY_NEXT_DELTA = effect_order_key("ET_FAST_SKILL")
P_SET_SELF_COOLDOWN = effect_order_key("ET_SKILL_CD")
P_TRANSFER_MODS = effect_order_variant_key("ET_SWAP_STAT", "transfer_mods")


PAK_DATA_DIR = Path(__file__).resolve().parents[1] / "pak-public-kit" / "output" / "data"


@pytest.fixture(scope="module")
def pak() -> PakTables:
    return PakTables(PAK_DATA_DIR)


# ── core decoder ─────────────────────────────────────────────────────


def test_decode_family_axes_returns_none_for_unknown_effect(pak):
    """Effect not in EFFECT_CONF → None (caller routes to gap)."""
    assert decode_family_axes(99999999, pak.effect_conf, pak.buff_conf) is None


def test_decode_family_axes_returns_none_for_non_counter_effect(pak):
    """An unknown axis row falls through (caller hits structural)."""
    unhandled = next(
        eid
        for eid, rec in pak.effect_conf.items()
        if int(rec.get("effect_order", 0)) not in {
            ET_PURIFY,
            5,
            11,
            19,
            ET_COUNTER,
            32,
            37,
            ET_BUFF_CONVERT,
            44,
            47,
            ET_COPY_BUFF,
            51,
        }
    )
    assert decode_family_axes(unhandled, pak.effect_conf, pak.buff_conf) is None


@pytest.mark.parametrize("effect_id, handler, p0", [
    (1005030, P_HEAL_HP, 3000),
    (1011005, P_LIFE_DRAIN, 5000),
    (1019004, P_HEAL_ENERGY, 4),
    (1019028, P_HEAL_ENERGY, 2),
    (1032008, P_HIT_COUNT_DELTA, 8),
    (1037001, P_SET_SELF_COOLDOWN, 3),
    (1051001, P_PRIORITY_NEXT_DELTA, 1),
])
def test_decode_common_scalar_effect_families(pak, effect_id, handler, p0):
    outcome = decode_family_axes(effect_id, pak.effect_conf, pak.buff_conf)
    assert isinstance(outcome, EmitOutcome)
    assert outcome.primitive == handler
    assert outcome.p0 == p0
    assert (outcome.p1, outcome.p2, outcome.p3, outcome.stacks) == (0, 0, 0, 1)


def test_decode_zero_change_energy_is_explicit_energy_row(pak):
    """ET_CHANGE_ENERGY [0,0,0] is a declared zero delta, not a gap."""
    outcome = decode_family_axes(1019047, pak.effect_conf, pak.buff_conf)
    assert isinstance(outcome, EmitOutcome)
    assert outcome.primitive == P_HEAL_ENERGY
    assert (outcome.p0, outcome.p1, outcome.p2, outcome.p3, outcome.stacks) == (0, 0, 0, 0, 1)


@pytest.mark.parametrize("effect_id", [1034019, 1034020])
def test_decode_hero_event_count_buff_families(pak, effect_id):
    outcome = decode_family_axes(effect_id, pak.effect_conf, pak.buff_conf)
    assert isinstance(outcome, tuple)
    emit, timing = outcome
    assert isinstance(emit, EmitOutcome)
    assert emit.primitive == P_ENTRY_SELF_BUFF_BY_SOURCE_COUNT
    assert emit.p0 > 0
    assert emit.p1 > 0
    assert (emit.p2, emit.p3, emit.stacks) == (0, 0, 1)
    assert timing == pak_battle_event_key("BEVT_SDT")


@pytest.mark.parametrize("effect_id, handler", [
    (1044001, P_EXCHANGE_HP_RATIO),
    (1044002, P_TRANSFER_MODS),
    (1047002, P_EXCHANGE_MOVES),
])
def test_decode_mode_based_exchange_families(pak, effect_id, handler):
    outcome = decode_family_axes(effect_id, pak.effect_conf, pak.buff_conf)
    assert isinstance(outcome, EmitOutcome)
    assert outcome.primitive == handler
    assert (outcome.p0, outcome.p1, outcome.p2, outcome.p3, outcome.stacks) == (0, 0, 0, 0, 1)


@pytest.mark.parametrize("effect_id, handler, p0", [
    (1004002, P_DISPEL_DEBUFFS, 0),
    (1004065, P_DISPEL_DEBUFFS, 0),
    (1042008, P_DISPEL_MARKS, 0),
    (1042014, P_DISPEL_MARKS_TO_BURN, 5),
    (1050012, P_MIRROR_ENEMY_BUFFS, 0),
])
def test_decode_composite_effect_families_from_pak_shape(pak, effect_id, handler, p0):
    """Former exact-effect rows now resolve from effect_order + param shape."""
    outcome = decode_family_axes(effect_id, pak.effect_conf, pak.buff_conf)
    assert isinstance(outcome, EmitOutcome)
    assert outcome.primitive == handler
    assert outcome.p0 == p0
    assert (outcome.p1, outcome.p2, outcome.p3, outcome.stacks) == (0, 0, 0, 1)


def test_decode_counter_emits_install_counter_with_after_move_timing(pak):
    """Every ``effect_order=31`` record decodes to ``P_INSTALL_COUNTER``
    with the pak ``BEVT_BEFORE_HURT`` timing and the response skill_id from
    ``effect_param[0].params[0]``."""
    o31_ids = [
        eid
        for eid, rec in pak.effect_conf.items()
        if int(rec.get("effect_order", 0)) == ET_COUNTER
    ]
    assert o31_ids, "pak has no effect_order=31 records (counter family empty)"
    for eid in o31_ids:
        outcome = decode_family_axes(eid, pak.effect_conf, pak.buff_conf)
        assert outcome is not None, f"effect_order=31 record {eid} not covered"
        # Tuple shape: (EmitOutcome, timing_override).
        assert isinstance(outcome, tuple)
        emit, timing = outcome
        assert isinstance(emit, EmitOutcome)
        assert emit.primitive == P_INSTALL_COUNTER
        assert timing == COUNTER_INSTALL_TIMING == pak_battle_event_key("BEVT_BEFORE_HURT")
        # p0 is the response skill_id, taken from pak directly.
        rec = pak.effect_conf[eid]
        expected_csid = int(rec["effect_param"][0]["params"][0])
        assert emit.p0 == expected_csid
        # Other params zeroed — P_INSTALL_COUNTER reads only p0.
        assert (emit.p1, emit.p2, emit.p3) == (0, 0, 0)
        assert emit.stacks == 1


# ── coverage against the pre-7B exact rules ────────────────────────


def test_family_axes_covers_every_previous_exact_counter_id(pak):
    """The ids that the historical exact-effect table covered
    via ``P_INSTALL_COUNTER`` must still resolve to the same emit row
    via the new family decoder — byte-for-byte same handler + p0.

    Backstop against accidentally narrowing the family decoder; the
    pak-axis path replaces the exact rules, not augments them.
    """
    # Reconstruct the pre-7B exact-rule list directly from pak:
    # every effect_order=31 record with a valid 70xxxxx response.
    expected: dict[int, int] = {}
    for eid, rec in pak.effect_conf.items():
        if int(rec.get("effect_order", 0)) != ET_COUNTER:
            continue
        params = rec.get("effect_param") or []
        if not params or not isinstance(params[0], dict):
            continue
        inner = params[0].get("params") or []
        if not inner:
            continue
        csid = int(inner[0])
        if 7000000 <= csid < 8000000:
            expected[eid] = csid

    for eid, expected_csid in expected.items():
        outcome = decode_family_axes(eid, pak.effect_conf, pak.buff_conf)
        assert outcome is not None
        emit, timing = outcome
        assert emit.primitive == P_INSTALL_COUNTER
        assert emit.p0 == expected_csid
        assert timing == pak_battle_event_key("BEVT_BEFORE_HURT")


# ── invariant: no P_INSTALL_COUNTER exact semantic row ─────────────


def test_no_exact_effect_semantics_table():
    """Post-migration: runtime effect rows must not use an exact id table."""
    path = Path(__file__).resolve().parents[1] / "roco" / "compiler_v2" / "semantics.py"
    assert not path.exists()


# ── orchestrator integration ───────────────────────────────────────


def test_generate_effect_rows_emits_install_counter_for_o31(pak):
    """End-to-end: a fake ``skill_result`` that references an
    ``effect_order=31`` effect_id produces an install-counter row at
    the after-move pak BattleEvent even when the entry's ``cast_moment`` is non-11.

    Locks the timing_override behaviour preserved from the historical
    exact rules: cast_moment 6/7/12 still install at 11.
    """
    from roco.compiler_v2.effect_codegen import generate_effect_rows

    # Pick an effect_order=31 id with a known response skill_id.
    eid = next(
        eid
        for eid, rec in pak.effect_conf.items()
        if int(rec.get("effect_order", 0)) == ET_COUNTER
    )
    csid = int(pak.effect_conf[eid]["effect_param"][0]["params"][0])

    skill = {
        "skill_result": [
            {
                "effect_id": eid,
                "result_target_type": 1,
                "cast_moment": 7,  # deliberately non-11 to exercise override
                "success_rate": 10000,
            }
        ]
    }
    rows, gaps = generate_effect_rows(skill, pak)
    assert gaps == []
    assert len(rows) == 1
    handler, timing, target, rate, p0, p1, p2, p3 = rows[0]
    assert handler == P_INSTALL_COUNTER
    assert timing == pak_battle_event_key("BEVT_BEFORE_HURT")
    assert target == 1
    assert rate == 10000
    assert p0 == csid
    assert (p1, p2, p3) == (0, 0, 0)
