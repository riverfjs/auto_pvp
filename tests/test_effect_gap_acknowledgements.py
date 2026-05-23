"""Validation + drift tests for Phase 3 effect-gap acknowledgements.

Tests mirror the structure of ``test_buff_immunity.py``: accept paths
drive the loader against the real ``effect_gap_acknowledgements.jsonl``
plus the real pak tables; reject paths construct a tmp jsonl + stub pak
table and assert each loader failure condition raises.

The accept paths additionally cross-check the loader's canonical
``gap_match`` keys against the live ``effect_gaps`` rows so both
directions of the strict bidirectional gate are exercised in CI.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from roco.compiler_v2.effect_codegen.acknowledgements_loader import (
    Acknowledgement,
    canonical_gap_key,
    canonical_gap_key_from_row,
    load_acknowledgements,
)
from roco.data.validation import compute_gap_validation_errors


ROOT = Path(__file__).resolve().parents[1]
REAL_RULES = ROOT / "roco" / "compiler_v2" / "rules" / "effect_gap_acknowledgements.jsonl"
REAL_DB = ROOT / "_db" / "data.db"


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n",
        encoding="utf-8",
    )


def _stub_skill_conf(rows: list[dict]) -> dict[int, dict]:
    """Build a SKILL_CONF stub.

    Each input row carries either ``effect_ids`` (shorthand: target=1,
    moment=11, rate=10000 for every entry) or ``entries`` (list of full
    skill_result entry dicts the caller wants verbatim, e.g. to test the
    cast_moment / result_target_type / success_rate discriminators).
    """
    table: dict[int, dict] = {}
    for r in rows:
        if "entries" in r:
            sr = list(r["entries"])
        else:
            sr = [
                {"effect_id": eid, "result_target_type": 1, "cast_moment": 11,
                 "success_rate": 10000, "buff_group_level": 1}
                for eid in r.get("effect_ids", [])
            ]
        table[int(r["id"])] = {
            "id": r["id"],
            "name": r["name"],
            "desc": r["desc"],
            "skill_result": sr,
        }
    return table


def _stub_effect_conf(rows: list[dict]) -> dict[int, dict]:
    """Build an EFFECT_CONF stub for family_key derivation tests."""
    return {int(r["id"]): r for r in rows}


def _stub_buff_conf(rows: list[dict]) -> dict[int, dict]:
    """Build a BUFF_CONF stub for prefix family_key derivation tests."""
    return {int(r["id"]): r for r in rows}


def _ok_gap_match(effect_id: int = 1034014) -> dict:
    return {
        "source_type": "ability",
        "source_name": "身经百练",
        "primitive": f"effect_{effect_id}",
        "timing_code": 11,
        "reason": "effect_type_3_state_change",
        "params": {
            "effect_id": effect_id,
            "buff_id": None,
            "target_type": 1,
            "success_rate": 10000,
        },
    }


def _ok_skill_stub(*, sid: int = 200178, name: str = "身经百练",
                   desc: str = "己方精灵每应对1次，自己入场时水系和武系技能威力+20%。",
                   effect_ids: list[int] | None = None,
                   entries: list[dict] | None = None) -> dict[str, dict[int, dict]]:
    """Build the default stub pak.  Always includes the EFFECT_CONF entry
    needed by the family_key derivation check so the happy-path ack row
    validates end-to-end without callers having to repeat it."""
    if entries is not None:
        skill_row = {"id": sid, "name": name, "desc": desc, "entries": entries}
    else:
        skill_row = {"id": sid, "name": name, "desc": desc,
                     "effect_ids": effect_ids if effect_ids is not None else [1034014]}
    return {
        "SKILL_CONF": _stub_skill_conf([skill_row]),
        "EFFECT_CONF": _stub_effect_conf(
            [{"id": 1034014, "type": 3, "effect_order": 34}]
        ),
        "BUFF_CONF": _stub_buff_conf([]),
    }


def _ok_row(**overrides) -> dict:
    rec = {
        "gap_match": _ok_gap_match(),
        "audit": {"family_key": "effect_conf:t3:o34"},
        "status": "evidence_available_deferred",
        "evidence": {
            "source_table": "SKILL_CONF",
            "source_id": 200178,
            "desc_quote": "己方精灵每应对1次，自己入场时水系和武系技能威力+20%。",
            "anchor_keywords": ["入场", "%"],
        },
        "owner": "phase3",
        "note": "test row",
    }
    rec.update(overrides)
    return rec


# ── accept: real rules + real pak ─────────────────────────────────────────


def test_accept_real_rules():
    acks = load_acknowledgements()
    assert acks, "expected at least one acknowledgement in the real rules file"
    # Every ack must satisfy the unique-key invariant
    keys = [k for a in acks for k in a.expected_canonical_keys]
    assert len(keys) == len(set(keys))


@pytest.mark.skipif(not REAL_DB.exists(), reason="_db/data.db not built")
def test_real_acks_exactly_match_current_used_gaps():
    """ack_keys must equal current effect_gaps used set (no unack, no stale)."""
    acks = load_acknowledgements()
    ack_keys: set[str] = set()
    for a in acks:
        if a.allow_stale:
            continue
        ack_keys.update(a.expected_canonical_keys)
    con = sqlite3.connect(REAL_DB)
    rows = con.execute(
        "SELECT source_type, source_name, primitive, timing_code, params_json, reason "
        "FROM effect_gaps WHERE used_count > 0"
    ).fetchall()
    gap_keys = {
        canonical_gap_key_from_row({
            "source_type": r[0], "source_name": r[1], "primitive": r[2],
            "timing_code": r[3], "params_json": r[4], "reason": r[5],
        })
        for r in rows
    }
    assert gap_keys - ack_keys == set(), f"unacked used gaps: {gap_keys - ack_keys}"
    assert ack_keys - gap_keys == set(), f"stale acks: {ack_keys - gap_keys}"


@pytest.mark.skipif(not REAL_DB.exists(), reason="_db/data.db not built")
def test_real_acks_no_over_match():
    """Each ack must match exactly its declared expected count of gap rows."""
    acks = load_acknowledgements()
    con = sqlite3.connect(REAL_DB)
    rows = con.execute(
        "SELECT source_type, source_name, primitive, timing_code, params_json, reason "
        "FROM effect_gaps WHERE used_count > 0"
    ).fetchall()
    gap_keys = {
        canonical_gap_key_from_row({
            "source_type": r[0], "source_name": r[1], "primitive": r[2],
            "timing_code": r[3], "params_json": r[4], "reason": r[5],
        })
        for r in rows
    }
    for ack in acks:
        expected = len(ack.expected_canonical_keys)
        actual = sum(1 for k in ack.expected_canonical_keys if k in gap_keys)
        if ack.allow_stale and actual == 0:
            continue
        assert actual == expected, (
            f"line {ack.line_no}: expected {expected} matches got {actual}"
        )


# ── reject: each condition from the loader spec ───────────────────────────


def test_reject_unknown_status(tmp_path):
    rec = _ok_row(status="garbage")
    fake = tmp_path / "ack.jsonl"
    _write_jsonl(fake, [rec])
    with pytest.raises(RuntimeError, match=r"unknown status"):
        load_acknowledgements(rules_path=fake, pak_tables=_ok_skill_stub())


def test_reject_unknown_source_table(tmp_path):
    rec = _ok_row()
    rec["evidence"] = {**rec["evidence"], "source_table": "MADE_UP"}
    fake = tmp_path / "ack.jsonl"
    _write_jsonl(fake, [rec])
    with pytest.raises(RuntimeError, match=r"source_table"):
        load_acknowledgements(rules_path=fake, pak_tables=_ok_skill_stub())


def test_reject_gap_match_missing_field(tmp_path):
    rec = _ok_row()
    rec["gap_match"].pop("timing_code")
    fake = tmp_path / "ack.jsonl"
    _write_jsonl(fake, [rec])
    with pytest.raises(RuntimeError, match=r"missing required fields"):
        load_acknowledgements(rules_path=fake, pak_tables=_ok_skill_stub())


def test_reject_duplicate_canonical_key(tmp_path):
    rec1 = _ok_row()
    rec2 = _ok_row(note="dup")
    fake = tmp_path / "ack.jsonl"
    _write_jsonl(fake, [rec1, rec2])
    with pytest.raises(RuntimeError, match=r"duplicate gap canonical key"):
        load_acknowledgements(rules_path=fake, pak_tables=_ok_skill_stub())


def test_reject_desc_quote_mismatch(tmp_path):
    rec = _ok_row()
    rec["evidence"] = {**rec["evidence"], "desc_quote": rec["evidence"]["desc_quote"] + "X"}
    fake = tmp_path / "ack.jsonl"
    _write_jsonl(fake, [rec])
    with pytest.raises(RuntimeError, match=r"desc_quote.*does not match"):
        load_acknowledgements(rules_path=fake, pak_tables=_ok_skill_stub())


def test_reject_deferred_empty_anchors(tmp_path):
    rec = _ok_row()
    rec["evidence"] = {**rec["evidence"], "anchor_keywords": []}
    fake = tmp_path / "ack.jsonl"
    _write_jsonl(fake, [rec])
    with pytest.raises(RuntimeError, match=r"requires non-empty anchor_keywords"):
        load_acknowledgements(rules_path=fake, pak_tables=_ok_skill_stub())


def test_reject_anchor_not_in_desc(tmp_path):
    rec = _ok_row()
    rec["evidence"] = {**rec["evidence"], "anchor_keywords": ["不存在的词"]}
    fake = tmp_path / "ack.jsonl"
    _write_jsonl(fake, [rec])
    with pytest.raises(RuntimeError, match=r"is not a substring of desc_quote"):
        load_acknowledgements(rules_path=fake, pak_tables=_ok_skill_stub())


def test_reject_weak_missing_weak_reason(tmp_path):
    rec = _ok_row(status="evidence_available_weak")
    rec["evidence"] = {**rec["evidence"], "anchor_keywords": []}
    # no weak_reason
    fake = tmp_path / "ack.jsonl"
    _write_jsonl(fake, [rec])
    with pytest.raises(RuntimeError, match=r"weak_reason"):
        load_acknowledgements(rules_path=fake, pak_tables=_ok_skill_stub())


def test_reject_missing_probe_summary(tmp_path):
    rec = _ok_row(status="evidence_missing")
    rec.pop("evidence")
    # no probe_summary
    fake = tmp_path / "ack.jsonl"
    _write_jsonl(fake, [rec])
    with pytest.raises(RuntimeError, match=r"probe_summary"):
        load_acknowledgements(rules_path=fake, pak_tables=_ok_skill_stub())


def test_reject_confirmed_ignored_missing_reason(tmp_path):
    rec = _ok_row(status="confirmed_ignored")
    rec.pop("evidence")
    fake = tmp_path / "ack.jsonl"
    _write_jsonl(fake, [rec])
    with pytest.raises(RuntimeError, match=r"ignored_reason"):
        load_acknowledgements(rules_path=fake, pak_tables=_ok_skill_stub())


def test_reject_unrelated_evidence_source_id(tmp_path):
    """desc_quote valid + anchors valid, but skill_result has no gap token."""
    rec = _ok_row()
    pak = _ok_skill_stub(effect_ids=[9999999])  # NOT 1034014
    fake = tmp_path / "ack.jsonl"
    _write_jsonl(fake, [rec])
    with pytest.raises(RuntimeError, match=r"no entry matching gap_match"):
        load_acknowledgements(rules_path=fake, pak_tables=pak)


def test_reject_evidence_name_mismatch(tmp_path):
    """Direct-reference check: source_id row name must equal gap_match.source_name."""
    rec = _ok_row()
    pak = {"SKILL_CONF": _stub_skill_conf([
        {
            "id": 200178,
            "name": "其它技能",  # not 身经百练
            "desc": "己方精灵每应对1次，自己入场时水系和武系技能威力+20%。",
            "effect_ids": [1034014],
        }
    ])}
    fake = tmp_path / "ack.jsonl"
    _write_jsonl(fake, [rec])
    with pytest.raises(RuntimeError, match=r"name.*does not match gap_match.source_name"):
        load_acknowledgements(rules_path=fake, pak_tables=pak)


def test_reject_family_key_not_in_catalog(tmp_path):
    rec = _ok_row()
    rec["audit"] = {"family_key": "bogus_family"}
    fake = tmp_path / "ack.jsonl"
    _write_jsonl(fake, [rec])
    with pytest.raises(RuntimeError, match=r"audit.family_key.*not present"):
        load_acknowledgements(
            rules_path=fake,
            pak_tables=_ok_skill_stub(),
            known_family_keys={"effect_conf:t3:o34"},
        )


def test_reject_allow_multi_match_missing_expected(tmp_path):
    rec = _ok_row(allow_multi_match=True)
    # no expected_matches
    fake = tmp_path / "ack.jsonl"
    _write_jsonl(fake, [rec])
    with pytest.raises(RuntimeError, match=r"expected_matches"):
        load_acknowledgements(rules_path=fake, pak_tables=_ok_skill_stub())


def test_reject_expected_matches_without_allow_multi(tmp_path):
    rec = _ok_row(expected_matches=[_ok_gap_match()])
    fake = tmp_path / "ack.jsonl"
    _write_jsonl(fake, [rec])
    with pytest.raises(RuntimeError, match=r"expected_matches must be omitted"):
        load_acknowledgements(rules_path=fake, pak_tables=_ok_skill_stub())


# ── drift: audit report contains the new sections ─────────────────────────


def test_audit_md_has_ack_sections():
    """Generated audit md should expose all four ack status sections."""
    md_path = ROOT / "_docs" / "effect_family_audit.md"
    md = md_path.read_text(encoding="utf-8")
    for status in (
        "evidence_available_deferred",
        "evidence_available_weak",
        "evidence_missing",
        "confirmed_ignored",
    ):
        assert f"## Acknowledgements — {status}" in md, status
    assert "matched gap rows" in md


# ── family_key derivation (P2-1 regression) ───────────────────────────────


def test_reject_family_key_mislabel_via_derivation(tmp_path):
    """Catalog membership is not enough: the family_key must be the one the
    derivation rule would assign to this exact gap_match."""
    rec = _ok_row()
    rec["audit"] = {"family_key": "effect_conf:t1:o4"}  # real key, wrong gap
    fake = tmp_path / "ack.jsonl"
    _write_jsonl(fake, [rec])
    with pytest.raises(RuntimeError, match=r"does not match the family_key derived"):
        load_acknowledgements(
            rules_path=fake,
            pak_tables=_ok_skill_stub(),
            known_family_keys={"effect_conf:t1:o4", "effect_conf:t3:o34"},
        )


def test_reject_prefix_family_disagrees_with_buff(tmp_path):
    """prefix_<N> primitive must match base_ids[0]//1000 of params.buff_id."""
    gm = {
        "source_type": "ability",
        "source_name": "X",
        "primitive": "prefix_2003",
        "timing_code": 11,
        "reason": "prefix_2003_unmapped",
        "params": {"effect_id": None, "buff_id": 12345, "target_type": 1, "success_rate": 10000},
    }
    rec = {
        "gap_match": gm,
        "audit": {"family_key": "buff_conf_direct:prefix_2003"},
        "status": "confirmed_ignored",
        "ignored_reason": "test",
        "owner": "test",
        "note": "",
    }
    # BUFF_CONF[12345] has base_ids[0]//1000 == 9999, not 2003.
    pak = {
        "SKILL_CONF": _stub_skill_conf([]),
        "EFFECT_CONF": _stub_effect_conf([]),
        "BUFF_CONF": _stub_buff_conf([{"id": 12345, "buff_base_ids": [9999000]}]),
    }
    fake = tmp_path / "ack.jsonl"
    _write_jsonl(fake, [rec])
    with pytest.raises(RuntimeError, match=r"primitive prefix 2003 disagrees"):
        load_acknowledgements(rules_path=fake, pak_tables=pak)


# ── direct-reference full entry match (P2-2 regression) ───────────────────


def test_reject_evidence_matches_sibling_entry_cast_moment(tmp_path):
    """Two skill_result entries with same effect_id but different cast_moment:
    ack pointing at cast_moment=11 must fail when its gap_match.timing_code=26."""
    rec = _ok_row()
    rec["gap_match"]["timing_code"] = 26  # gap wants moment 26
    entries = [
        {"effect_id": 1034014, "result_target_type": 1, "cast_moment": 11,
         "success_rate": 10000, "buff_group_level": 1},
        # No entry with cast_moment 26 → ack should fail
    ]
    pak = _ok_skill_stub(entries=entries)
    fake = tmp_path / "ack.jsonl"
    _write_jsonl(fake, [rec])
    with pytest.raises(RuntimeError, match=r"no entry matching gap_match"):
        load_acknowledgements(rules_path=fake, pak_tables=pak)


def test_reject_evidence_matches_sibling_entry_target_type(tmp_path):
    rec = _ok_row()
    rec["gap_match"]["params"] = {**rec["gap_match"]["params"], "target_type": 3}
    entries = [
        {"effect_id": 1034014, "result_target_type": 1, "cast_moment": 11,
         "success_rate": 10000, "buff_group_level": 1},
    ]
    pak = _ok_skill_stub(entries=entries)
    fake = tmp_path / "ack.jsonl"
    _write_jsonl(fake, [rec])
    with pytest.raises(RuntimeError, match=r"no entry matching gap_match"):
        load_acknowledgements(rules_path=fake, pak_tables=pak)


def test_reject_evidence_matches_sibling_entry_success_rate(tmp_path):
    rec = _ok_row()
    rec["gap_match"]["params"] = {**rec["gap_match"]["params"], "success_rate": 5000}
    entries = [
        {"effect_id": 1034014, "result_target_type": 1, "cast_moment": 11,
         "success_rate": 10000, "buff_group_level": 1},
    ]
    pak = _ok_skill_stub(entries=entries)
    fake = tmp_path / "ack.jsonl"
    _write_jsonl(fake, [rec])
    with pytest.raises(RuntimeError, match=r"no entry matching gap_match"):
        load_acknowledgements(rules_path=fake, pak_tables=pak)


def test_accept_when_one_of_many_entries_matches_fully(tmp_path):
    """When skill_result has multiple entries with same effect_id but only one
    matches the full discriminator set, that single matching entry suffices."""
    rec = _ok_row()
    rec["gap_match"]["timing_code"] = 26
    entries = [
        {"effect_id": 1034014, "result_target_type": 1, "cast_moment": 11,
         "success_rate": 10000, "buff_group_level": 1},
        {"effect_id": 1034014, "result_target_type": 1, "cast_moment": 26,
         "success_rate": 10000, "buff_group_level": 1},
    ]
    pak = _ok_skill_stub(entries=entries)
    fake = tmp_path / "ack.jsonl"
    _write_jsonl(fake, [rec])
    acks = load_acknowledgements(rules_path=fake, pak_tables=pak)
    assert len(acks) == 1


# ── validation regression: stale, under-match, allow_stale (P3) ───────────


def _build_ack(
    *,
    line_no: int,
    primitive: str = "effect_1034014",
    source_name: str = "身经百练",
    timing: int = 11,
    target_type: int = 1,
    success_rate: int = 10000,
    allow_stale: bool = False,
    expected_matches: list[dict] | None = None,
) -> Acknowledgement:
    gm = {
        "source_type": "ability",
        "source_name": source_name,
        "primitive": primitive,
        "timing_code": timing,
        "reason": "effect_type_3_state_change",
        "params": {
            "effect_id": 1034014,
            "buff_id": None,
            "target_type": target_type,
            "success_rate": success_rate,
        },
    }
    return Acknowledgement(
        gap_match=gm,
        audit={"family_key": "effect_conf:t3:o34"},
        status="confirmed_ignored",
        evidence=None,
        owner="test",
        note="",
        weak_reason=None,
        probe_summary=None,
        ignored_reason="test",
        allow_multi_match=expected_matches is not None,
        expected_matches=expected_matches or [],
        allow_stale=allow_stale,
        stale_reason="opt-in" if allow_stale else None,
        line_no=line_no,
    )


def _make_gap_row(
    *,
    primitive: str = "effect_1034014",
    source_name: str = "身经百练",
    timing: int = 11,
    target_type: int = 1,
    success_rate: int = 10000,
    used_count: int = 5,
) -> dict:
    return {
        "source_type": "ability",
        "source_name": source_name,
        "primitive": primitive,
        "timing_code": timing,
        "params_json": json.dumps({
            "effect_id": 1034014,
            "buff_id": None,
            "target_type": target_type,
            "success_rate": success_rate,
        }),
        "reason": "effect_type_3_state_change",
        "used_count": used_count,
    }


def test_validation_passes_when_ack_set_equals_gap_set():
    gap = _make_gap_row()
    ack = _build_ack(line_no=1)
    assert compute_gap_validation_errors([gap], [ack]) == []


def test_validation_reports_stale_ack():
    """Ack present, gap rows empty → stale + under-match errors."""
    ack = _build_ack(line_no=1)
    errors = compute_gap_validation_errors([], [ack])
    assert any("no longer match any used effect_gaps" in e for e in errors)
    assert any("expected 1 match(es), got 0" in e for e in errors)


def test_validation_tolerates_stale_when_allow_stale_set():
    """allow_stale=true suppresses both stale + under-match when 0 matches."""
    ack = _build_ack(line_no=1, allow_stale=True)
    errors = compute_gap_validation_errors([], [ack])
    assert errors == []


def test_validation_reports_unacked_gap():
    gap = _make_gap_row()
    errors = compute_gap_validation_errors([gap], [])
    assert any("no acknowledgement" in e for e in errors)


def test_validation_reports_under_match_with_multi_match():
    """allow_multi_match=true with N entries but only K of them match gap set
    must report the under-match difference."""
    em1 = {
        "source_type": "ability",
        "source_name": "身经百练",
        "primitive": "effect_1034014",
        "timing_code": 11,
        "reason": "effect_type_3_state_change",
        "params": {"effect_id": 1034014, "buff_id": None, "target_type": 1, "success_rate": 10000},
    }
    em2 = dict(em1)
    em2["params"] = {**em1["params"], "target_type": 3}  # second variant
    ack = _build_ack(line_no=1, expected_matches=[em1, em2])
    # Only em1 has a matching gap row
    errors = compute_gap_validation_errors([_make_gap_row(target_type=1)], [ack])
    assert any("expected 2 match(es), got 1" in e for e in errors)


def test_validation_reports_over_match_via_duplicate_acks_caught_earlier():
    """Loader rejects duplicate keys, so over-match against a single gap is
    structurally impossible without using allow_multi_match.  This test
    documents the property: two distinct acks pointing at the same gap key
    each have expected=1, and the gap matches both, so each reports
    expected=1 got=1 — the *loader* is the layer that prevents the duplication."""
    ack_a = _build_ack(line_no=1)
    ack_b = _build_ack(line_no=2)  # same canonical key as ack_a
    gap = _make_gap_row()
    errors = compute_gap_validation_errors([gap], [ack_a, ack_b])
    # Both acks each match the one gap row — no over-match error from the
    # validator alone.  The loader-level duplicate-key check is the
    # safety net here.
    assert errors == []


def test_validation_partial_stale_with_allow_stale_still_fails_when_one_match_present():
    """allow_stale only tolerates the *fully-stale* case (0 matches).  If an
    allow_multi_match ack with 2 expected matches has 1 match in the gap
    set, allow_stale must NOT suppress the under-match."""
    em1 = {
        "source_type": "ability",
        "source_name": "身经百练",
        "primitive": "effect_1034014",
        "timing_code": 11,
        "reason": "effect_type_3_state_change",
        "params": {"effect_id": 1034014, "buff_id": None, "target_type": 1, "success_rate": 10000},
    }
    em2 = dict(em1)
    em2["params"] = {**em1["params"], "target_type": 3}
    ack = _build_ack(line_no=1, expected_matches=[em1, em2], allow_stale=True)
    errors = compute_gap_validation_errors([_make_gap_row(target_type=1)], [ack])
    assert any("expected 2 match(es), got 1" in e for e in errors)
