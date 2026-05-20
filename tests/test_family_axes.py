"""Tests for the pak-axis family decoder module.

The ``effect_order=31`` counter family is the first axis to land here
(Phase 7B), replacing 76 hand-written ``H_INSTALL_COUNTER`` rules in
``exact_effects.jsonl``.  These tests pin the migration contract:

* The decoder fires for every ``effect_order=31`` record in pak —
  not just the 76 previously-covered ids.
* The emitted row matches the exact-rule shape it replaces
  (``handler=H_INSTALL_COUNTER``, ``p0=response_skill_id``, timing
  override = 11).
* The pre-migration ack file does not regress: counter effect_ids that
  were *not* in ``exact_effects.jsonl`` previously surfaced as gaps
  (type=2 emitted spurious H_DAMAGE rows or type=3 went to gap) — the
  new decoder covers them silently.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from roco.compiler.effect_codegen import family_axes
from roco.compiler.effect_codegen.family_axes import (
    COUNTER_INSTALL_TIMING,
    ET_COUNTER,
    decode_family_axes,
)
from roco.compiler.effect_codegen.outcomes import EmitOutcome
from roco.compiler.effect_codegen.pak import PakTables
from roco.generated.handler_indices import H_INSTALL_COUNTER


PAK_DATA_DIR = Path(__file__).resolve().parents[1] / "pak-public-kit" / "output" / "data"


@pytest.fixture(scope="module")
def pak() -> PakTables:
    return PakTables(PAK_DATA_DIR)


# ── core decoder ─────────────────────────────────────────────────────


def test_decode_family_axes_returns_none_for_unknown_effect(pak):
    """Effect not in EFFECT_CONF → None (caller routes to gap)."""
    assert decode_family_axes(99999999, pak.effect_conf, pak.buff_conf) is None


def test_decode_family_axes_returns_none_for_non_counter_effect(pak):
    """An ``effect_order != 31`` row falls through (caller hits structural)."""
    non_counter = next(
        eid
        for eid, rec in pak.effect_conf.items()
        if int(rec.get("effect_order", 0)) != ET_COUNTER
    )
    assert decode_family_axes(non_counter, pak.effect_conf, pak.buff_conf) is None


def test_decode_counter_emits_install_counter_with_timing_11(pak):
    """Every ``effect_order=31`` record decodes to ``H_INSTALL_COUNTER``
    with timing_override 11 (AFTER_MOVE) and the response skill_id from
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
        assert emit.handler_idx == H_INSTALL_COUNTER
        assert timing == COUNTER_INSTALL_TIMING == 11
        # p0 is the response skill_id, taken from pak directly.
        rec = pak.effect_conf[eid]
        expected_csid = int(rec["effect_param"][0]["params"][0])
        assert emit.p0 == expected_csid
        # Other params zeroed — H_INSTALL_COUNTER reads only p0.
        assert (emit.p1, emit.p2, emit.p3) == (0, 0, 0)
        assert emit.stacks == 1


# ── coverage against the pre-7B exact rules ────────────────────────


def test_family_axes_covers_every_previous_exact_counter_id(pak):
    """The 76 ids that the historical ``exact_effects.jsonl`` covered
    via ``H_INSTALL_COUNTER`` must still resolve to the same emit row
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
        assert emit.handler_idx == H_INSTALL_COUNTER
        assert emit.p0 == expected_csid
        assert timing == 11


# ── invariant: no H_INSTALL_COUNTER in exact_effects.jsonl ─────────


def test_exact_effects_jsonl_no_install_counter():
    """Post-migration: ``exact_effects.jsonl`` must not contain any
    ``H_INSTALL_COUNTER`` row.  Anything in pak's counter family routes
    through :func:`decode_family_axes`; re-adding a hand-written rule
    would double-emit (or shadow) and is a bug.
    """
    path = (
        Path(__file__).resolve().parents[1]
        / "roco" / "compiler" / "rules" / "exact_effects.jsonl"
    )
    with path.open("r", encoding="utf-8") as fp:
        for line_no, raw in enumerate(fp, 1):
            raw = raw.strip()
            if not raw or raw.startswith("#"):
                continue
            rec = json.loads(raw)
            assert rec.get("handler") != "H_INSTALL_COUNTER", (
                f"exact_effects.jsonl line {line_no}: H_INSTALL_COUNTER "
                f"row {rec.get('effect_id')} found — counter family is "
                f"now decoded by family_axes; remove the row or extend "
                f"the family decoder."
            )


# ── orchestrator integration ───────────────────────────────────────


def test_generate_effect_rows_emits_install_counter_for_o31(pak):
    """End-to-end: a fake ``skill_result`` that references an
    ``effect_order=31`` effect_id produces an install-counter row at
    timing 11 even when the entry's ``cast_moment`` is non-11.

    Locks the timing_override behaviour preserved from the historical
    exact rules: cast_moment 6/7/12 still install at 11.
    """
    from roco.compiler.effect_codegen import generate_effect_rows

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
    rows, ignored, gaps = generate_effect_rows(skill, pak)
    assert ignored == []
    assert gaps == []
    assert len(rows) == 1
    handler, timing, target, rate, p0, p1, p2, p3 = rows[0]
    assert handler == H_INSTALL_COUNTER
    assert timing == 11  # override forced to AFTER_MOVE
    assert target == 1
    assert rate == 10000
    assert p0 == csid
    assert (p1, p2, p3) == (0, 0, 0)
