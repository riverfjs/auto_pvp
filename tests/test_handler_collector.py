"""Tests for compiler primitive-axis resolution."""

from __future__ import annotations

import pytest

from roco.common.primitive_keys import buff_type_key
from roco.compiler_v2.build import build_static_bundle
from roco.compiler_v2.primitive_axes import (
    BUFF_TYPE_ALIASES,
    MARK_NOTE_MARKS,
    PREFIX_TYPE_ALIASES,
    resolve_primitive_axes,
)

P_DAMAGE_REDUCTION = buff_type_key("BFT_DAMNUM_CHANGE")
P_SELF_BUFF = buff_type_key("BFT_KILL_BUFF")


def test_resolve_primitive_axes_runs_on_lua_enums():
    axes = resolve_primitive_axes(build_static_bundle().lua_enums)
    assert len(axes.buffbase_order) == 78
    assert len(axes.prefix) == 3
    assert len(axes.raw["mark_note"]) == 12
    assert axes.prefix[2011] == P_DAMAGE_REDUCTION
    assert axes.prefix[2046] == P_SELF_BUFF
    assert "湿润印记" in axes.raw["mark_note"]
    assert axes.base_id == {}


def test_declared_buff_type_symbols_exist_in_lua_enum():
    enum = build_static_bundle().lua_enums["BuffType"]
    missing = sorted((set(BUFF_TYPE_ALIASES) | set(PREFIX_TYPE_ALIASES)) - set(enum))
    assert missing == []


def test_mark_notes_are_known_and_unique():
    names = list(MARK_NOTE_MARKS.values())
    assert len(names) == len(set(names))


def test_missing_lua_bufftype_raises():
    with pytest.raises(RuntimeError, match="missing Enum.BuffType"):
        resolve_primitive_axes({})
