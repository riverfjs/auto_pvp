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

from roco.compiler.effect_codegen.acknowledgements_loader import (
    canonical_gap_key,
    canonical_gap_key_from_row,
    load_acknowledgements,
)


ROOT = Path(__file__).resolve().parents[1]
REAL_RULES = ROOT / "roco" / "compiler" / "rules" / "effect_gap_acknowledgements.jsonl"
REAL_DB = ROOT / "_db" / "data.db"


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n",
        encoding="utf-8",
    )


def _stub_skill_conf(rows: list[dict]) -> dict[int, dict]:
    """Build a SKILL_CONF stub from a list of (id, name, desc, [(effect_id, ...), ...])."""
    table: dict[int, dict] = {}
    for r in rows:
        table[int(r["id"])] = {
            "id": r["id"],
            "name": r["name"],
            "desc": r["desc"],
            "skill_result": [
                {"effect_id": eid, "result_target_type": 1, "cast_moment": 11,
                 "success_rate": 10000, "buff_group_level": 1}
                for eid in r.get("effect_ids", [])
            ],
        }
    return table


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
                   effect_ids: list[int] | None = None) -> dict[str, dict[int, dict]]:
    if effect_ids is None:
        effect_ids = [1034014]
    return {"SKILL_CONF": _stub_skill_conf([
        {"id": sid, "name": name, "desc": desc, "effect_ids": effect_ids}
    ])}


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
    pak = {"SKILL_CONF": _stub_skill_conf([
        {
            "id": 200178,
            "name": "身经百练",
            "desc": "己方精灵每应对1次，自己入场时水系和武系技能威力+20%。",
            "effect_ids": [9999999],  # NOT 1034014
        }
    ])}
    fake = tmp_path / "ack.jsonl"
    _write_jsonl(fake, [rec])
    with pytest.raises(RuntimeError, match=r"unrelated to the declared gap_match"):
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
