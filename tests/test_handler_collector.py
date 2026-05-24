"""Tests for the AST-based handler-axis decorator collector.

The collector reads ``@handles_buff`` / ``@handles_prefix`` declarations
on every ``op_*`` function across the kernel op modules and exposes them
as flat dispatch tables.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from roco.compiler_v2.handler_axes import (
    _scan_module,
    collect_handler_axes,
    resolve_handler_axes,
)


@pytest.fixture()
def tmp_op_module(tmp_path: Path) -> Path:
    src = textwrap.dedent('''
        from roco.engine.kernel.op_meta import handles_buff, handles_prefix

        @handles_buff([("BFT_ATTR_CHANGE", "STAT_MOD"), ("BFT_BAN", "LOCK_SWITCH")])
        def op_self_buff(ctx, row):
            pass

        @handles_buff([("BFT_PET_TRANSE", "FORCE_SWITCH")])
        def op_force_switch(ctx, row):
            pass

        @handles_prefix([("BFT_DAMNUM_CHANGE", "DAMAGE_REDUCE")])
        def op_damage_reduction(ctx, row):
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
    assert result["buff_type"] == {
        "BFT_ATTR_CHANGE": ("op_self_buff", "STAT_MOD"),
        "BFT_BAN": ("op_self_buff", "LOCK_SWITCH"),
        "BFT_PET_TRANSE": ("op_force_switch", "FORCE_SWITCH"),
    }


def test_scan_module_collects_prefix(tmp_op_module: Path):
    result = _scan_module(tmp_op_module, "fake_ops")
    assert result["prefix_type"] == {"BFT_DAMNUM_CHANGE": ("op_damage_reduction", "DAMAGE_REDUCE")}


def test_scan_module_skips_undecorated_ops(tmp_op_module: Path):
    """``op_*`` functions without any handles_* decorator must not appear."""
    result = _scan_module(tmp_op_module, "fake_ops")
    for axis_table in result.values():
        assert "op_nodecorator" not in {handler for handler, _ in axis_table.values()}


# ── error surface ─────────────────────────────────────────────────────────


def test_non_literal_argument_raises(tmp_path: Path):
    src = textwrap.dedent('''
        from roco.engine.kernel.op_meta import handles_buff
        SOME_TYPE = "BFT_ATTR_CHANGE"

        @handles_buff([(SOME_TYPE, "STAT_MOD")])
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

        @handles_buff([("BFT_ATTR_CHANGE", "STAT_MOD", "extra")])
        def op_self_buff(ctx, row):
            pass
    ''').strip() + "\n"
    p = tmp_path / "bad_ops.py"
    p.write_text(src, encoding="utf-8")
    with pytest.raises(RuntimeError, match="\\(key, str\\) tuple"):
        _scan_module(p, "bad_ops")


def test_conflicting_keys_within_module_raise(tmp_path: Path):
    src = textwrap.dedent('''
        from roco.engine.kernel.op_meta import handles_buff

        @handles_buff([("BFT_ATTR_CHANGE", "STAT_MOD")])
        def op_a(ctx, row):
            pass

        @handles_buff([("BFT_ATTR_CHANGE", "OTHER")])
        def op_b(ctx, row):
            pass
    ''').strip() + "\n"
    p = tmp_path / "bad_ops.py"
    p.write_text(src, encoding="utf-8")
    with pytest.raises(RuntimeError, match="declared twice"):
        _scan_module(p, "bad_ops")


# ── real scan ─────────────────────────────────────────────────────────────


def test_collect_handler_axes_runs_on_real_op_mods():
    """The real engine owns semantic coverage metadata, not numeric ids."""
    axes = collect_handler_axes()
    assert {axis: len(bucket) for axis, bucket in axes.items()} == {
        "buff_type": 78,
        "prefix_type": 3,
    }
    assert "BFT_ATTR_CHANGE" in axes["buff_type"]
    assert "BFT_DAMNUM_CHANGE" in axes["prefix_type"]
    assert "base_id" not in axes


def test_resolve_handler_axes_resolves_names_to_indices(monkeypatch):
    """When a decorator references a real handler, the index lookup wins."""
    fake_axes = {
        "buff_type": {"BFT_ATTR_CHANGE": ("op_self_buff", "STAT_MOD")},
        "prefix_type": {},
    }
    monkeypatch.setattr(
        "roco.compiler_v2.handler_axes.collect_handler_axes",
        lambda op_modules=(): fake_axes,
    )
    handler_indices = {"H_SELF_BUFF": 4, "H_NOOP": 0}
    resolved = resolve_handler_axes(
        handler_indices,
        {"BuffType": {"BFT_ATTR_CHANGE": 1}},
        op_modules=(),
    )
    assert resolved.buffbase_order == {1: 4}
    assert resolved.prefix == {}
    assert resolved.base_id == {}


def test_resolve_handler_axes_unknown_handler_raises(monkeypatch):
    fake_axes = {
        "buff_type": {"BFT_ATTR_CHANGE": ("op_nonexistent_handler", "X")},
        "prefix_type": {},
    }
    monkeypatch.setattr(
        "roco.compiler_v2.handler_axes.collect_handler_axes",
        lambda op_modules=(): fake_axes,
    )
    with pytest.raises(RuntimeError, match="not in handler_indices"):
        resolve_handler_axes(
            {"H_NOOP": 0},
            {"BuffType": {"BFT_ATTR_CHANGE": 1}},
            op_modules=(),
        )
