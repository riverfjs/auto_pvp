"""Tests for the BUFFBASE_CONF → buffbase_params.py codegen.

The generated module is consumed by handlers at runtime to read pak's
literal ``buffbase_param`` values without parsing JSON.  These tests
gate the codegen and the on-disk artifact.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from roco.compiler.codegen.buffbase_params_codegen import (
    BUFFBASE_PARAMS_PATH,
    _normalize_slot,
    build_buffbase_tables,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
PAK_BUFFBASE_PATH = (
    REPO_ROOT / "pak-public-kit" / "output" / "data" / "BinData" / "BUFFBASE_CONF.json"
)


# ── slot normalisation ────────────────────────────────────────────────────


def test_normalize_scalar_slot():
    assert _normalize_slot({"params": [29]}) == 29


def test_normalize_multi_element_slot():
    assert _normalize_slot({"params": [2, 3]}) == (2, 3)


def test_normalize_empty_slot():
    """Empty params list collapses to empty tuple, not None."""
    assert _normalize_slot({"params": []}) == ()


def test_normalize_bare_list_slot():
    """Tolerant of a raw list shape if pak ever omits the dict wrapper."""
    assert _normalize_slot([10]) == 10
    assert _normalize_slot([1, 2, 3]) == (1, 2, 3)


# ── full table build ──────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def tables() -> dict:
    return build_buffbase_tables()


def test_every_pak_base_id_is_present(tables: dict):
    """Every record in BUFFBASE_CONF must appear in all three dicts."""
    with PAK_BUFFBASE_PATH.open("r", encoding="utf-8") as fp:
        raw = json.load(fp)
    pak_ids = {int(k) for k in raw["RocoDataRows"]}
    assert set(tables["params"]) == pak_ids
    assert set(tables["order"]) == pak_ids
    assert set(tables["trigger"]) == pak_ids


def test_buffbase_order_matches_pak(tables: dict):
    """Sanity: the generated ``BUFFBASE_ORDER`` mirrors pak.buffbase_order."""
    with PAK_BUFFBASE_PATH.open("r", encoding="utf-8") as fp:
        raw = json.load(fp)
    for k, rec in raw["RocoDataRows"].items():
        assert tables["order"][int(k)] == int(rec.get("buffbase_order") or 0)


def test_known_attr_change_params(tables: dict):
    """buffbase_order=1 stat-mod base ids encode (stat_idx, dir, magnitude)."""
    # 2001001 "物攻等级提升10" — pak says [29, 0, 1000].
    assert tables["params"][2001001] == (29, 0, 1000)
    assert tables["order"][2001001] == 1


def test_known_counter_install_params(tables: dict):
    """buffbase_order=64 records carry effect_param[0]=response_skill_id."""
    # buffbase_order=64 (BFT_STRENGTHEN_THE_SKILL); pick any to check shape.
    o64 = {bid for bid, o in tables["order"].items() if o == 64}
    assert o64, "pak has no buffbase_order=64 — fixture mismatch"
    for bid in list(o64)[:5]:
        params = tables["params"][bid]
        # We don't pin exact values per pak update — just shape: non-empty
        # tuple with int / int-tuple slots.
        assert isinstance(params, tuple) and len(params) > 0


def test_trigger_type_defaults_to_zero(tables: dict):
    """Records without trigger_type in JSON get 0 (not None)."""
    # buffbase_order=1 records typically have no trigger_type.
    for bid, order in tables["order"].items():
        if order == 1:
            assert isinstance(tables["trigger"][bid], int)


# ── on-disk artifact ──────────────────────────────────────────────────────


def test_generated_module_exists():
    assert BUFFBASE_PARAMS_PATH.exists()


def test_generated_module_imports():
    """Import the generated module and verify the public dicts are there."""
    from roco.generated import buffbase_params as bp  # type: ignore
    assert hasattr(bp, "BUFFBASE_PARAMS")
    assert hasattr(bp, "BUFFBASE_ORDER")
    assert hasattr(bp, "BUFFBASE_TRIGGER_TYPE")
    # Cross-check at least one known entry survives the round-trip.
    assert bp.BUFFBASE_PARAMS[2001001] == (29, 0, 1000)
    assert bp.BUFFBASE_ORDER[2001001] == 1
