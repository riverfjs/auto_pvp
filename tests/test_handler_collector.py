"""Tests for compiler primitive-axis resolution."""

from __future__ import annotations

import pytest

from roco.common.primitive_keys import buff_type_key
from roco.compiler_v2.build import build_static_bundle
from roco.compiler_v2.primitive_axes import (
    BUFF_TYPE_SYMBOLS,
    PREFIX_TYPE_SYMBOLS,
    resolve_primitive_axes,
)
from roco.compiler_v2.static_artifacts.marks import mark_desc_by_idx

P_DAMAGE_REDUCTION = buff_type_key("BFT_DAMNUM_CHANGE")
P_SELF_BUFF = buff_type_key("BFT_KILL_BUFF")


def test_resolve_primitive_axes_runs_on_lua_enums():
    axes = resolve_primitive_axes(build_static_bundle().lua_enums)
    assert len(axes.buffbase_order) == 78
    assert len(axes.prefix) == 3
    assert "mark_note" not in axes.raw
    assert axes.prefix[2011] == P_DAMAGE_REDUCTION
    assert axes.prefix[2046] == P_SELF_BUFF
    assert axes.base_id == {}


def test_declared_buff_type_symbols_exist_in_lua_enum():
    enum = build_static_bundle().lua_enums["BuffType"]
    missing = sorted((set(BUFF_TYPE_SYMBOLS) | set(PREFIX_TYPE_SYMBOLS)) - set(enum))
    assert missing == []


def test_mark_descriptions_are_structurally_derived_and_unique():
    desc_by_idx = mark_desc_by_idx()
    assert len(desc_by_idx) >= 11
    assert len(desc_by_idx.values()) == len(set(desc_by_idx.values()))


def test_missing_lua_bufftype_raises():
    with pytest.raises(RuntimeError, match="missing Enum.BuffType"):
        resolve_primitive_axes({})
