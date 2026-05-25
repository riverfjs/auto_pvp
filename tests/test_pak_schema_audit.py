"""Self-check tests for the pak schema mining audit.

These tests verify the read-only schema mining outputs: every pak
``(type, effect_order)`` tuple appears in the EFFECT_CONF section,
every ``buffbase_order`` appears in the BUFFBASE_CONF section, the
hand-written-rule debt analysis surfaces the known
``effect_order=31`` counter cluster, and the prefix-rule identity
``prefix - 2000 == buffbase_order`` holds for every current rule.

The audit itself does not drive runtime behavior, so these tests
gate against silent breakage of the mining report — not against
kernel semantics.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from roco.compiler_v2 import pak_schema_audit
from roco.compiler_v2.pak_schema_audit import (
    AUDIT_MD,
    PAK_BIN,
    SCHEMA_TABLES,
    _load_pak_table,
    buffbase_families,
    build_audit,
    detect_schema_drift,
    effect_conf_families,
    exact_rule_debt,
    main as run_pak_schema_audit,
    prefix_rule_debt,
    render_markdown,
)


# ── fixtures ──────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def effect_conf() -> dict[int, dict]:
    return _load_pak_table(PAK_BIN / "EFFECT_CONF.json")


@pytest.fixture(scope="module")
def buffbase_conf() -> dict[int, dict]:
    return _load_pak_table(PAK_BIN / "BUFFBASE_CONF.json")


@pytest.fixture(scope="module")
def buff_conf() -> dict[int, dict]:
    return _load_pak_table(PAK_BIN / "BUFF_CONF.json")


# ── schema drift ──────────────────────────────────────────────────


def test_schema_drift_covers_all_tables():
    """One row per logical table in SCHEMA_TABLES, with the expected keys."""
    drift = detect_schema_drift()
    assert {d["table"] for d in drift} == {name for name, _, _ in SCHEMA_TABLES}
    for d in drift:
        assert "shared_count" in d
        assert "lua_only" in d
        assert "json_only" in d


def test_schema_drift_buffbase_reports_editor_name_lua_only():
    """Current pak Lua still declares ``editor_name`` for BUFFBASE_CONF,
    but the JSON export no longer carries it.

    This is exactly why compiler_v2 must not resolve handlers through
    BUFFBASE_CONF.editor_name.
    """
    drift = detect_schema_drift()
    by_table = {d["table"]: d for d in drift}
    bb = by_table["BUFFBASE_CONF"]
    assert bb["lua_only"] == ["editor_name"]
    assert bb["json_only"] == []


# ── EFFECT_CONF families ──────────────────────────────────────────


def test_effect_conf_families_cover_every_type_order(effect_conf):
    """Every ``(type, effect_order)`` tuple present in EFFECT_CONF.json
    must appear in the audit output — guards against partial mining."""
    expected = {
        (int(rec.get("type", 0)), int(rec.get("effect_order", 0)))
        for rec in effect_conf.values()
    }
    fams = effect_conf_families(effect_conf, {}, {}, {})
    actual = {(f["type"], f["effect_order"]) for f in fams}
    assert actual == expected


def test_effect_conf_o31_carries_all_counter_records(effect_conf):
    """The ``effect_order=31`` family must report the full pak counter
    population — 203 records as of the current pak dump.  Locks the
    central headline for the counter-family migration planned for 7B."""
    fams = effect_conf_families(effect_conf, {}, {}, {})
    o31 = [f for f in fams if f["effect_order"] == 31]
    assert len(o31) == 3  # one per pak ``type`` (1, 2, 3)
    total = sum(f["count"] for f in o31)
    # Cross-check directly against the raw table — keeps the test robust
    # to pak data updates without hard-coding 203.
    expected = sum(
        1
        for rec in effect_conf.values()
        if int(rec.get("effect_order", -1)) == 31
    )
    assert total == expected


# ── BUFFBASE_CONF families ────────────────────────────────────────


def test_buffbase_families_cover_every_order(buffbase_conf, buff_conf):
    """Every ``buffbase_order`` value appearing in BUFFBASE_CONF.json
    must have a row in the audit's section 3."""
    expected = {
        int(rec.get("buffbase_order", 0))
        for rec in buffbase_conf.values()
    }
    fams = buffbase_families(buffbase_conf, buff_conf, {})
    actual = {f["buffbase_order"] for f in fams}
    assert actual == expected


def test_buffbase_families_count_total(buffbase_conf, buff_conf):
    """Sum of per-order counts equals total record count."""
    fams = buffbase_families(buffbase_conf, buff_conf, {})
    assert sum(f["count"] for f in fams) == len(buffbase_conf)


# ── rule debt ─────────────────────────────────────────────────────


def test_exact_rule_debt_h_install_counter_migrated_out():
    """Post-7B: ``H_INSTALL_COUNTER`` no longer appears in
    exact compiler semantic rules; compiler_v2 no longer owns behavior
    decoders.

    Locks the migration: re-adding a row by hand for any ``ET_COUNTER``
    effect would fail this test, surfacing the regression at audit time.
    """
    from roco.compiler_v2.pak_schema_audit import _load_exact_rules
    handlers = {r["handler"] for r in _load_exact_rules()}
    assert "H_INSTALL_COUNTER" not in handlers, (
        "H_INSTALL_COUNTER row in exact compiler semantics — the counter "
        "family belongs in the engine artifact linker, not compiler_v2."
    )


def test_exact_rule_debt_cluster_size_at_least_threshold(effect_conf):
    """Every migration_candidate entry has cluster_size >= threshold (3)."""
    from roco.compiler_v2.pak_schema_audit import _load_exact_rules
    exact_rules = _load_exact_rules()
    debt = exact_rule_debt(exact_rules, effect_conf, cluster_threshold=3)
    for r in debt:
        if r["migration_candidate"]:
            assert r["cluster_size"] >= 3
        elif r["effect_order"] >= 0:
            assert r["cluster_size"] < 3


def test_prefix_rule_debt_identity_universal(buffbase_conf):
    """For every engine prefix rule, the dominant ``buffbase_order`` satisfies
    ``prefix - 2000 == buffbase_order``.

    Locks the structural identity that motivates the 7C migration: the
    prefix axis is a literal restatement of buffbase_order, not an
    independent dimension.  If this ever fails, we have a prefix whose
    rule covers something other than its natural pak axis — needs
    review before 7C.
    """
    from roco.compiler_v2.pak_schema_audit import _load_prefix_rules
    prefix_rules, _ = _load_prefix_rules()
    debt = prefix_rule_debt(prefix_rules, buffbase_conf)
    non_identity = [r for r in debt if not r["implied_identity"]]
    assert not non_identity, (
        f"prefix rules whose dominant buffbase_order is NOT prefix-2000: "
        f"{[(r['prefix'], r['dominant_buffbase_order']) for r in non_identity]}"
    )


def test_prefix_rule_debt_only_mixed_remain(buffbase_conf):
    """Only the 3 prefixes whose buffbase_order distribution is *not*
    100% concentrated remain on the engine prefix axis.

    Regression guard: any prefix rule whose dominant order reaches 100%
    concentration is migration debt and should be moved to the
    buffbase_order axis.
    """
    from roco.compiler_v2.pak_schema_audit import _load_prefix_rules
    prefix_rules, _ = _load_prefix_rules()
    debt = prefix_rule_debt(prefix_rules, buffbase_conf)
    clean = [r for r in debt if r["clean_rewrite"]]
    assert clean == [], (
        f"engine prefix axis has {len(clean)} 100%-clean prefix(es) — "
        f"these should migrate to pak buffbase_order audit coverage: "
        f"{[r['prefix'] for r in clean]}"
    )
    # The 3 known-mixed prefixes are the entire post-7C set.
    assert {r["prefix"] for r in debt} == {2011, 2046, 2050}


# ── render + check mode ───────────────────────────────────────────


def test_render_markdown_is_deterministic():
    """Two consecutive renders with identical inputs produce identical bytes.

    The ``--check`` mode relies on this — any non-determinism (set
    iteration order, dict ordering) would make the gate fire on every
    rebuild.
    """
    a = build_audit()
    b = build_audit()
    assert a == b


def test_check_mode_clean():
    """``--check`` returns 0 when the on-disk audit matches a fresh build."""
    assert AUDIT_MD.exists(), (
        "_docs/pak_schema_audit.md missing — run "
        "`uv run python -m roco.compiler_v2.pak_schema_audit`"
    )
    assert run_pak_schema_audit(["--check"]) == 0


def test_check_mode_detects_stale(tmp_path, monkeypatch):
    """When the on-disk audit differs from a fresh build, ``--check``
    must return 1 and not silently overwrite the file."""
    stub = tmp_path / "stub.md"
    stub.write_text("nope\n", encoding="utf-8")
    monkeypatch.setattr(pak_schema_audit, "AUDIT_MD", stub)
    assert run_pak_schema_audit(["--check"]) == 1
    # The audit must not have been rewritten by --check.
    assert stub.read_text(encoding="utf-8") == "nope\n"


def test_check_mode_missing_file(tmp_path, monkeypatch):
    """Missing audit file → ``--check`` returns 1 (not crash)."""
    monkeypatch.setattr(pak_schema_audit, "AUDIT_MD", tmp_path / "absent.md")
    assert run_pak_schema_audit(["--check"]) == 1
