"""Tests for the BUFFBASE_CONF.buffbase_order axis of buff handler dispatch.

The buffbase_order axis is the pak-native primary lookup for direct
BUFF_CONF references.  The current compiler does not read JSONL seeds or
Python order tables; it collects engine-owned ``op_meta`` declarations
that reference stable ``Enum.BuffType`` symbols and resolves those
symbols through generated Lua data.

* The codegen join with BUFFBASE_CONF produces a base_id → handler map
  that the runtime classifier picks up before mixed-prefix dispatch.
* The 3 mixed prefixes left on the engine prefix axis are not
  silently shadowed by an over-broad buffbase_order rule.
* No compiler-owned ``buffbase_order -> handler`` table comes back.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from roco.compiler_v2.effect_codegen import classify as cls
from roco.compiler_v2.effect_codegen.classify import decode_buff_direct
from roco.compiler_v2.effect_codegen.outcomes import EmitOutcome, GapOutcome
from roco.compiler_v2.effect_codegen.params import pack_handler_params
from roco.compiler_v2.effect_codegen.pak import PakTables
from roco.compiler_v2.build import build_static_bundle
from roco.compiler_v2.handler_axes import collect_handler_axes, resolve_handler_axes
from roco.generated import handler_indices as hi


REPO_ROOT = Path(__file__).resolve().parents[1]
PREFIX_MAP_PATH = REPO_ROOT / "roco" / "generated" / "prefix_handler_map.json"
BUFFBASE_CONF_PATH = (
    REPO_ROOT / "pak-public-kit" / "output" / "data" / "BinData" / "BUFFBASE_CONF.json"
)


@pytest.fixture(scope="module")
def handler_indices() -> dict[str, int]:
    out = {k: int(v) for k, v in vars(hi).items() if k.startswith("H_") and isinstance(v, int)}
    return out


@pytest.fixture(scope="module")
def resolved_axes(handler_indices):
    return resolve_handler_axes(handler_indices, build_static_bundle().lua_enums)


@pytest.fixture(scope="module")
def buffbase_conf() -> dict[int, dict]:
    raw = json.loads(BUFFBASE_CONF_PATH.read_text(encoding="utf-8"))
    rows = raw.get("RocoDataRows", raw)
    return {int(k): v for k, v in rows.items()}


# ── handler-owned axis metadata ──────────────────────────────────────────


def test_engine_buff_type_axis_loads_78_entries(resolved_axes):
    """Locks the current engine coverage scope without a compiler seed table."""
    assert len(resolved_axes.buffbase_order) == 78


def test_hit_count_related_orders_are_not_broad_axes(resolved_axes):
    """These orders contain unsupported sub-shapes, so they must be exact or gap."""
    assert 17 not in resolved_axes.buffbase_order
    assert 45 not in resolved_axes.buffbase_order
    assert 91 not in resolved_axes.buffbase_order
    assert 115 not in resolved_axes.buffbase_order


def test_engine_orders_disjoint_from_mixed_prefixes(resolved_axes):
    """The 3 mixed prefixes' dominant orders are NOT in the
    buffbase_order axis; that's the whole reason they stay on the
    prefix layer."""
    seed = set(resolved_axes.buffbase_order)
    # prefix 2011 dominant order = 11; 2046 = 46; 2050 = 50.
    assert 11 not in seed
    assert 46 not in seed
    assert 50 not in seed


def test_engine_axis_handlers_all_resolve(handler_indices, resolved_axes):
    """Every handler declared on the engine axis exists in ``handler_indices.py``."""
    valid = set(handler_indices.values())
    for order, handler_idx in resolved_axes.buffbase_order.items():
        assert handler_idx in valid, (
            f"buffbase_order={order} resolves to handler_idx={handler_idx} "
            "which is not in handler_indices"
        )


def test_compiler_v2_has_no_buffbase_order_table():
    path = Path(__file__).resolve().parents[1] / "roco" / "compiler_v2" / "semantics.py"
    assert not path.exists()


# ── codegen join ──────────────────────────────────────────────────────────


def test_generated_base_id_via_order_map_size(resolved_axes, buffbase_conf):
    """Every BUFFBASE_CONF record whose ``buffbase_order`` is in the
    seed must appear in the resolved map.  Locks the join correctness:
    if the codegen ever drops base_ids silently, this test screams.
    """
    expected_count = sum(
        1
        for rec in buffbase_conf.values()
        if rec.get("buffbase_order") is not None
        and int(rec["buffbase_order"]) in resolved_axes.buffbase_order
    )
    data = json.loads(PREFIX_MAP_PATH.read_text(encoding="utf-8"))
    assert len(data["base_id_via_order_map"]) == expected_count


def test_generated_prefix_map_carries_via_order_block():
    """The runtime classifier reads from prefix_handler_map.json.  The
    new ``base_id_via_order_map`` block must be present and non-empty
    after gen_prefix_map runs."""
    data = json.loads(PREFIX_MAP_PATH.read_text(encoding="utf-8"))
    assert "base_id_via_order_map" in data
    assert len(data["base_id_via_order_map"]) > 0


# ── mixed-prefix axis invariants ─────────────────────────────────────────


def test_engine_prefix_axis_shrunk_to_mixed_only(resolved_axes):
    """Only the 3 mixed prefixes remain outside the buffbase_order axis.

    Exact base anchors are now derived structurally from pak rows instead
    of engine-owned display-name declarations.
    """
    assert set(resolved_axes.prefix) == {2011, 2046, 2050}, (
        f"engine prefix axis = {sorted(resolved_axes.prefix)} (expected "
        f"only the 3 mixed: 2011, 2046, 2050)"
    )
    assert resolved_axes.base_id == {}
    raw_axes = collect_handler_axes()
    assert set(raw_axes["prefix_type"]) == {
        "BFT_DAMNUM_CHANGE",
        "BFT_KILL_BUFF",
        "BFT_ENTER_BATTLE",
    }
    assert "base_id" not in raw_axes


# ── runtime classifier integration ────────────────────────────────────────


def test_runtime_classifier_routes_clean_prefix_via_via_order(buffbase_conf):
    """A buff_id whose ``buff_base_ids[0]`` is in a clean prefix range
    (e.g. 2001xxx → STAT_MOD/H_SELF_BUFF) must resolve through the
    ``BASE_ID_VIA_ORDER_MAP``, not the mixed-prefix map.  This is the
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


def test_runtime_classifier_routes_named_mark_buff_before_shared_base_id():
    """Canonical mark BUFF_CONF rows win before generic base-id dispatch.

    Poison mark shares base_id 2007001 with poison status, and moisture mark
    shares 2032007 with normal skill-cost reduction.  The generated
    BUFF_CONF.id map must keep those semantic identities separate.
    """
    pak = PakTables(REPO_ROOT / "pak-public-kit" / "output" / "data")
    assert cls.classify_buff_handler(20070011, pak.buff_conf) == hi.H_POISON_MARK
    assert cls.classify_buff_handler(20320070, pak.buff_conf) == hi.H_MOISTURE_MARK
    assert cls.classify_buff_handler(20320220, pak.buff_conf) == hi.H_PASSIVE_ENERGY_REDUCE
    assert 2032007 not in cls.BASE_ID_HANDLER_MAP


def test_runtime_classifier_routes_heal_reversal_exact_buff():
    """Order-146 heal reversal is an exact structural BUFF_CONF row, not a whole-prefix rule."""
    pak = PakTables(REPO_ROOT / "pak-public-kit" / "output" / "data")
    assert cls.classify_buff_handler(21460330, pak.buff_conf) == hi.H_ANTI_HEAL


def test_runtime_classifier_routes_cute_bench_cost_reduce_exact_buff():
    """Order-40 cute-stack trigger maps only the proved all-skill cost reducer."""
    pak = PakTables(REPO_ROOT / "pak-public-kit" / "output" / "data")
    handler = cls.classify_buff_handler(20400130, pak.buff_conf)
    assert handler == hi.H_CUTE_BENCH_COST_REDUCE
    assert pack_handler_params(handler, 20400130, pak.buff_conf) == (1, 0, 0, 0)


def test_runtime_classifier_routes_only_flat_hit_count_exact_buffs():
    """Order-45 hit-count rows are exact structural rows, not a whole-order rule."""
    pak = PakTables(REPO_ROOT / "pak-public-kit" / "output" / "data")

    plus = cls.classify_buff_handler(20450050, pak.buff_conf)
    minus = cls.classify_buff_handler(20450090, pak.buff_conf)
    assert plus == hi.H_HIT_COUNT_DELTA
    assert minus == hi.H_HIT_COUNT_DELTA
    assert pack_handler_params(plus, 20450050, pak.buff_conf) == (1, 0, 0, 0)
    assert pack_handler_params(minus, 20450090, pak.buff_conf) == (-1, 0, 0, 0)

    assert cls.classify_buff_handler(20450020, pak.buff_conf) == 0
    assert cls.classify_buff_handler(20450030, pak.buff_conf) == 0
    assert cls.classify_buff_handler(21150010, pak.buff_conf) == 0

    drive_outcome = decode_buff_direct(21150010, pak.buff_conf)[0]
    assert isinstance(drive_outcome, GapOutcome)
    assert drive_outcome.primitive == "prefix_2115"

    hit_outcome = decode_buff_direct(20450050, pak.buff_conf)[0]
    assert isinstance(hit_outcome, EmitOutcome)
    assert hit_outcome.p0 == 1


def test_runtime_classifier_falls_through_to_prefix_for_mixed(buffbase_conf):
    """Dominant base_ids in mixed prefixes (e.g. 2011's order=11 group)
    have NO buffbase_order entry — they fall through to the mixed
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
