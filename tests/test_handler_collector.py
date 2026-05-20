"""Tests for the AST-based handler-axis decorator collector.

The collector reads ``@handles_buff`` / ``@handles_prefix`` /
``@handles_base_id`` decorators on every ``op_*`` function across the
kernel op modules and exposes them as flat dispatch tables.  These
tests gate the collector independently from any handler that's
actually decorated — they exercise it on tiny synthetic source files
so the harness remains valid before Phase 8B starts decorating real
handlers.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from roco.compiler.codegen.handler_collector import (
    _scan_module,
    axes_with_handler_indices,
    collect_handler_axes,
)


@pytest.fixture()
def tmp_op_module(tmp_path: Path) -> Path:
    src = textwrap.dedent('''
        from roco.engine.kernel.op_meta import handles_buff, handles_prefix, handles_base_id

        @handles_buff([(1, "STAT_MOD"), (4, "LOCK_SWITCH")])
        def op_self_buff(ctx, row):
            pass

        @handles_buff([(48, "FORCE_SWITCH")])
        def op_force_switch(ctx, row):
            pass

        @handles_prefix([(2011, "DAMAGE_REDUCE")])
        def op_damage_reduction(ctx, row):
            pass

        @handles_base_id([(2005001, "leech base"), (2007002, "burn base")])
        def op_status_anchor(ctx, row):
            pass

        def op_nodecorator(ctx, row):
            pass
    ''').strip() + "\n"
    p = tmp_path / "fake_ops.py"
    p.write_text(src, encoding="utf-8")
    return p


# ── basic scan ────────────────────────────────────────────────────────────


def test_scan_module_collects_buffbase_orders(tmp_op_module: Path):
    result = _scan_module(tmp_op_module, "fake_ops")
    assert result["buffbase_order"] == {
        1: ("op_self_buff", "STAT_MOD"),
        4: ("op_self_buff", "LOCK_SWITCH"),
        48: ("op_force_switch", "FORCE_SWITCH"),
    }


def test_scan_module_collects_prefix(tmp_op_module: Path):
    result = _scan_module(tmp_op_module, "fake_ops")
    assert result["prefix"] == {2011: ("op_damage_reduction", "DAMAGE_REDUCE")}


def test_scan_module_collects_base_ids(tmp_op_module: Path):
    result = _scan_module(tmp_op_module, "fake_ops")
    assert result["base_id"] == {
        2005001: ("op_status_anchor", "leech base"),
        2007002: ("op_status_anchor", "burn base"),
    }


def test_scan_module_skips_undecorated_ops(tmp_op_module: Path):
    """``op_*`` functions without any handles_* decorator must not appear."""
    result = _scan_module(tmp_op_module, "fake_ops")
    for axis_table in result.values():
        assert "op_nodecorator" not in {handler for handler, _ in axis_table.values()}


# ── error surface ─────────────────────────────────────────────────────────


def test_non_literal_argument_raises(tmp_path: Path):
    src = textwrap.dedent('''
        from roco.engine.kernel.op_meta import handles_buff
        SOME_ORDER = 1

        @handles_buff([(SOME_ORDER, "STAT_MOD")])
        def op_self_buff(ctx, row):
            pass
    ''').strip() + "\n"
    p = tmp_path / "bad_ops.py"
    p.write_text(src, encoding="utf-8")
    with pytest.raises(RuntimeError, match="not a literal"):
        _scan_module(p, "bad_ops")


def test_wrong_tuple_shape_raises(tmp_path: Path):
    src = textwrap.dedent('''
        from roco.engine.kernel.op_meta import handles_buff

        @handles_buff([(1, "STAT_MOD", "extra")])
        def op_self_buff(ctx, row):
            pass
    ''').strip() + "\n"
    p = tmp_path / "bad_ops.py"
    p.write_text(src, encoding="utf-8")
    with pytest.raises(RuntimeError, match="\\(int, str\\) tuple"):
        _scan_module(p, "bad_ops")


def test_conflicting_keys_within_module_raise(tmp_path: Path):
    src = textwrap.dedent('''
        from roco.engine.kernel.op_meta import handles_buff

        @handles_buff([(1, "STAT_MOD")])
        def op_a(ctx, row):
            pass

        @handles_buff([(1, "OTHER")])
        def op_b(ctx, row):
            pass
    ''').strip() + "\n"
    p = tmp_path / "bad_ops.py"
    p.write_text(src, encoding="utf-8")
    with pytest.raises(RuntimeError, match="declared twice"):
        _scan_module(p, "bad_ops")


# ── empty real scan (pre-8B) ──────────────────────────────────────────────


def test_collect_handler_axes_runs_on_real_op_mods():
    """The full scan must not crash on the current undecorated kernel."""
    axes = collect_handler_axes()
    assert set(axes.keys()) == {"buffbase_order", "prefix", "base_id"}
    # Before Phase 8B lands the decorators, every axis is empty.
    # This test will flip to non-empty in 8B, which is the intended signal.
    for axis, bucket in axes.items():
        assert isinstance(bucket, dict)


def test_axes_with_handler_indices_resolves_names_to_indices(monkeypatch):
    """When a decorator references a real handler, the index lookup wins."""
    fake_axes = {
        "buffbase_order": {1: ("op_self_buff", "STAT_MOD")},
        "prefix": {},
        "base_id": {},
    }
    monkeypatch.setattr(
        "roco.compiler.codegen.handler_collector.collect_handler_axes",
        lambda op_modules=(): fake_axes,
    )
    handler_indices = {"H_SELF_BUFF": 4, "H_NOOP": 0}
    resolved = axes_with_handler_indices(handler_indices, op_modules=())
    assert resolved["buffbase_order"] == {1: 4}
    assert resolved["prefix"] == {}
    assert resolved["base_id"] == {}


def test_axes_with_handler_indices_unknown_handler_raises(monkeypatch):
    fake_axes = {
        "buffbase_order": {99: ("op_nonexistent_handler", "X")},
        "prefix": {},
        "base_id": {},
    }
    monkeypatch.setattr(
        "roco.compiler.codegen.handler_collector.collect_handler_axes",
        lambda op_modules=(): fake_axes,
    )
    with pytest.raises(RuntimeError, match="not in handler_indices"):
        axes_with_handler_indices({"H_NOOP": 0}, op_modules=())
