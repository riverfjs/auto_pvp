"""Tests for the BUFFBASE_CONF.buffbase_order axis of buff handler dispatch.

The buffbase_order axis is the pak-native primary lookup for direct
BUFF_CONF references (introduced in Phase 7C, replacing 88 of 91
``prefix_handlers.jsonl`` entries).  These tests gate the migration
boundary:

* Every row in ``rules/buffbase_order_handlers.jsonl`` resolves to a
  known kernel handler and a unique ``buffbase_order``.
* The codegen join with BUFFBASE_CONF produces a base_id → handler map
  that the runtime classifier picks up before the legacy prefix path.
* The 3 mixed prefixes left in ``prefix_handlers.jsonl`` are not
  silently shadowed by an over-broad buffbase_order rule.
* No clean (100%-concentrated) prefix remains in
  ``prefix_handlers.jsonl`` — those are migration debt.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from roco.compiler.codegen import buffbase_orders
from roco.compiler.codegen.buffbase_orders import (
    BUFFBASE_ORDER_SEED_PATH,
    _load_seed,
    build_base_id_via_order_map,
    seed_orders,
)
from roco.compiler.effect_codegen import classify as cls
from roco.generated import handler_indices as hi


REPO_ROOT = Path(__file__).resolve().parents[1]
PREFIX_HANDLERS_PATH = REPO_ROOT / "roco" / "compiler" / "rules" / "prefix_handlers.jsonl"
PREFIX_MAP_PATH = REPO_ROOT / "roco" / "generated" / "prefix_handler_map.json"
BUFFBASE_CONF_PATH = (
    REPO_ROOT / "pak-public-kit" / "output" / "data" / "BinData" / "BUFFBASE_CONF.json"
)


@pytest.fixture(scope="module")
def handler_indices() -> dict[str, int]:
    out = {k: int(v) for k, v in vars(hi).items() if k.startswith("H_") and isinstance(v, int)}
    return out


@pytest.fixture(scope="module")
def buffbase_conf() -> dict[int, dict]:
    raw = json.loads(BUFFBASE_CONF_PATH.read_text(encoding="utf-8"))
    rows = raw.get("RocoDataRows", raw)
    return {int(k): v for k, v in rows.items()}


# ── seed loader ───────────────────────────────────────────────────────────


def test_seed_loads_88_entries(handler_indices):
    """Locks the migration's headline scope — 88 prefixes flipped axis."""
    seed = _load_seed(handler_indices)
    assert len(seed) == 88


def test_seed_orders_disjoint_from_mixed_prefixes(handler_indices):
    """The 3 mixed prefixes' dominant orders are NOT in the
    buffbase_order seed; that's the whole reason they stayed at the
    legacy prefix layer."""
    seed = seed_orders(handler_indices)
    # prefix 2011 dominant order = 11; 2046 = 46; 2050 = 50.
    assert 11 not in seed
    assert 46 not in seed
    assert 50 not in seed


def test_seed_handlers_all_resolve(handler_indices):
    """Every handler name in the seed exists in ``handler_indices.py``."""
    seed = _load_seed(handler_indices)
    valid = set(handler_indices.values())
    for order, handler_idx in seed.items():
        assert handler_idx in valid, (
            f"buffbase_order={order} resolves to handler_idx={handler_idx} "
            "which is not in handler_indices"
        )


def test_seed_path_exists():
    assert BUFFBASE_ORDER_SEED_PATH.exists(), (
        "rules/buffbase_order_handlers.jsonl missing — required for the "
        "7C dispatch axis"
    )


# ── codegen join ──────────────────────────────────────────────────────────


def test_build_base_id_via_order_map_size(handler_indices, buffbase_conf):
    """Every BUFFBASE_CONF record whose ``buffbase_order`` is in the
    seed must appear in the resolved map.  Locks the join correctness:
    if the codegen ever drops base_ids silently, this test screams.
    """
    seed = _load_seed(handler_indices)
    expected_count = sum(
        1
        for rec in buffbase_conf.values()
        if rec.get("buffbase_order") is not None
        and int(rec["buffbase_order"]) in seed
    )
    actual = build_base_id_via_order_map(handler_indices)
    assert len(actual) == expected_count


def test_generated_prefix_map_carries_via_order_block():
    """The runtime classifier reads from prefix_handler_map.json.  The
    new ``base_id_via_order_map`` block must be present and non-empty
    after gen_prefix_map runs."""
    data = json.loads(PREFIX_MAP_PATH.read_text(encoding="utf-8"))
    assert "base_id_via_order_map" in data
    assert len(data["base_id_via_order_map"]) > 0


# ── prefix_handlers.jsonl post-7C invariants ─────────────────────────────


def test_prefix_handlers_jsonl_shrunk_to_mixed_only():
    """After 7C, only the 3 mixed prefixes + the 8 hand-curated base_id
    overrides remain.  Re-adding a clean prefix rule should fail this
    test and force the contributor to put it in
    ``buffbase_order_handlers.jsonl`` instead."""
    prefixes_seen: set[int] = set()
    base_ids_seen: set[int] = set()
    with PREFIX_HANDLERS_PATH.open("r", encoding="utf-8") as fp:
        for raw in fp:
            raw = raw.strip()
            if not raw or raw.startswith("#"):
                continue
            rec = json.loads(raw)
            if "prefix" in rec:
                prefixes_seen.add(int(rec["prefix"]))
            elif "base_id" in rec:
                base_ids_seen.add(int(rec["base_id"]))
    assert prefixes_seen == {2011, 2046, 2050}, (
        f"prefix_handlers.jsonl prefixes = {sorted(prefixes_seen)} (expected "
        f"only the 3 mixed: 2011, 2046, 2050)"
    )
    # base_id overrides are independent — assert count to catch
    # accidental loss but allow legitimate growth.
    assert len(base_ids_seen) >= 8


# ── runtime classifier integration ────────────────────────────────────────


def test_runtime_classifier_routes_clean_prefix_via_via_order(buffbase_conf):
    """A buff_id whose ``buff_base_ids[0]`` is in a clean prefix range
    (e.g. 2001xxx → STAT_MOD/H_SELF_BUFF) must resolve through the
    ``BASE_ID_VIA_ORDER_MAP``, not the legacy prefix map.  This is the
    central post-migration contract.
    """
    # Find a stat-mod base_id (prefix 2001, order 1).
    target_bid = next(
        bid for bid, rec in buffbase_conf.items()
        if bid // 1000 == 2001 and int(rec.get("buffbase_order", 0)) == 1
    )
    # Synthesize a buff_conf dict referencing only that base_id.
    buff_conf_stub = {99999999: {"buff_base_ids": [target_bid]}}
    h = cls.classify_buff_handler(99999999, buff_conf_stub)
    assert h == hi.H_SELF_BUFF
    # And the resolution path must be via_order_map, not prefix_map.
    assert target_bid in cls.BASE_ID_VIA_ORDER_MAP
    assert 2001 not in cls.PREFIX_HANDLER_MAP


def test_runtime_classifier_falls_through_to_prefix_for_mixed(buffbase_conf):
    """Dominant base_ids in mixed prefixes (e.g. 2011's order=11 group)
    have NO buffbase_order entry — they fall through to the legacy
    prefix layer and resolve via PREFIX_HANDLER_MAP[2011]."""
    # Find a 2011 base_id with order==11 (the dominant order, which is
    # NOT in the seed because 2011 is the mixed prefix).
    target_bid = next(
        bid for bid, rec in buffbase_conf.items()
        if bid // 1000 == 2011 and int(rec.get("buffbase_order", 0)) == 11
    )
    assert target_bid not in cls.BASE_ID_VIA_ORDER_MAP
    buff_conf_stub = {99999999: {"buff_base_ids": [target_bid]}}
    h = cls.classify_buff_handler(99999999, buff_conf_stub)
    assert h == hi.H_DAMAGE_REDUCTION
    assert 2011 in cls.PREFIX_HANDLER_MAP


def test_runtime_classifier_outlier_routes_to_via_order_handler(buffbase_conf):
    """Outliers in mixed prefixes (e.g. base_id 2050011 with order=48)
    now resolve via the buffbase_order axis to H_FORCE_SWITCH — fixing
    a pre-7C silent miscompile where prefix 2050 was returning
    H_SELF_BUFF for a force-switch primitive.
    """
    # base_id 2050011: editor_name='闪电步吹飞自己', buffbase_order=48
    target_bid = 2050011
    assert target_bid in cls.BASE_ID_VIA_ORDER_MAP
    buff_conf_stub = {99999999: {"buff_base_ids": [target_bid]}}
    h = cls.classify_buff_handler(99999999, buff_conf_stub)
    assert h == hi.H_FORCE_SWITCH
