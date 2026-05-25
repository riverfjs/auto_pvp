"""Tests for the BUFFBASE_CONF.buffbase_order axis audit artifact.

The buffbase_order axis is a pak-native audit view for direct BUFF_CONF
references.  The current compiler does not read JSONL seeds or Python order
tables; it resolves primitive-axis ``Enum.BuffType`` symbols through generated
Lua data.

* The codegen join with BUFFBASE_CONF produces a base_id → primitive map
  for reviewing generated pak coverage before mixed-prefix dispatch.
* The 3 mixed prefixes left on the prefix axis are not
  silently shadowed by an over-broad buffbase_order rule.
* No compiler-owned ``buffbase_order -> handler`` table comes back.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from roco.common.primitive_keys import (
    buff_ref_key,
    buff_type_key,
    effect_ref_key,
)
from roco.common.entry_sources import ENTRY_SOURCE_EQUIPPED_ELEMENT, entry_source_code
from roco.common.enums import AbilityFlag, Element
from roco.compiler_v2.effect_codegen import classify as cls
from roco.compiler_v2.effect_codegen import generate_effect_rows
from roco.data.ability_flags_from_effects import load_ability_flags_from_effects
from roco.compiler_v2.effect_codegen.classify import decode_buff_direct
from roco.compiler_v2.effect_codegen.outcomes import EmitOutcome
from roco.compiler_v2.effect_codegen.pak import PakTables
from roco.compiler_v2.build import build_static_bundle
from roco.compiler_v2.primitive_axes import PREFIX_TYPE_SYMBOLS, resolve_primitive_axes
from roco.compiler_v2.timing_keys import pak_cast_moment_key
from roco.engine.artifacts.linked_op import LinkGapError
from roco.engine.artifacts.primitive_linker import link_primitive_row, link_primitive_rows
from roco.engine.kernel.op_rows import TIMING_HOOK_BEFORE_MOVE, TIMING_PAK_SDT

P_ANTI_HEAL = buff_ref_key(21460330)
P_ACTIVE_IMMUNITY_BUFF = buff_ref_key(20030010)
P_CUTE_BENCH_COST_REDUCE = buff_ref_key(20400130)
P_CUTE_HIT_PER_STACK = buff_ref_key(20910020)
P_BFT_O_T = buff_type_key("BFT_O_T")
P_DAMAGE_REDUCTION = buff_type_key("BFT_DAMNUM_CHANGE")
P_FORCE_SWITCH = buff_type_key("BFT_PET_TRANSE")
P_HIT_COUNT_PER_POISON_EFFECT = buff_ref_key(20910010)
P_MOISTURE_MARK = buff_ref_key(20320070)
P_PASSIVE_ENERGY_REDUCE = buff_type_key("BFT_CHANGE_SKILL_ENERGY_COST")
P_POISON_MARK = buff_ref_key(20070011)
P_SELF_BUFF = buff_type_key("BFT_ATTR_CHANGE")
P_SLOT_SKILL_MOD_EFFECT = effect_ref_key(1083001)
P_SLOT_SKILL_MOD_BUFF = buff_ref_key(21150010)


REPO_ROOT = Path(__file__).resolve().parents[1]
PRIMITIVE_MAP_PATH = REPO_ROOT / "roco" / "generated" / "primitive_map.json"
BUFFBASE_CONF_PATH = (
    REPO_ROOT / "pak-public-kit" / "output" / "data" / "BinData" / "BUFFBASE_CONF.json"
)


def _linked_tuple(row: tuple, source_name: str = "fixture") -> tuple:
    linked = link_primitive_row(row, source_name=source_name)
    return (
        linked.op_name,
        linked.timing,
        linked.target,
        linked.rate,
        *linked.runtime_args(),
    )


def _linked_tuples(row: tuple, source_name: str = "fixture") -> list[tuple]:
    return [
        (
            linked.op_name,
            linked.timing,
            linked.target,
            linked.rate,
            *linked.runtime_args(),
        )
        for linked in link_primitive_rows(row, source_name=source_name)
    ]


@pytest.fixture(scope="module")
def resolved_axes():
    return resolve_primitive_axes(build_static_bundle().lua_enums)


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


def test_primitive_axis_values_are_nonempty(resolved_axes):
    """Every compiler primitive-axis entry resolves to a primitive string."""
    for order, primitive in resolved_axes.buffbase_order.items():
        assert isinstance(order, int)
        assert primitive


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
    data = json.loads(PRIMITIVE_MAP_PATH.read_text(encoding="utf-8"))
    assert len(data["base_id_via_order_map"]) == expected_count


def test_generated_prefix_map_carries_via_order_block():
    """The generated audit artifact mirrors the pak-source primitive map."""
    data = json.loads(PRIMITIVE_MAP_PATH.read_text(encoding="utf-8"))
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
    assert set(PREFIX_TYPE_SYMBOLS) == {
        "BFT_DAMNUM_CHANGE",
        "BFT_KILL_BUFF",
        "BFT_ENTER_BATTLE",
    }


# ── audit classifier integration ──────────────────────────────────────────


def test_audit_classifier_routes_clean_prefix_via_via_order(buffbase_conf):
    """A buff_id whose ``buff_base_ids[0]`` is in a clean prefix range
    (e.g. 2001xxx → BFT_ATTR_CHANGE) must resolve through the
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
    h = cls.classify_buff_primitive(99999999, buff_conf_stub)
    assert h == P_SELF_BUFF
    # And the resolution path must be via_order_map, not prefix_map.
    assert target_bid in cls.BASE_ID_VIA_ORDER_MAP
    assert 2001 not in cls.PREFIX_PRIMITIVE_MAP


def test_runtime_classifier_routes_named_mark_buff_before_shared_base_id():
    """Canonical mark BUFF_CONF rows win before generic base-id dispatch.

    Poison mark shares base_id 2007001 with poison status, and moisture mark
    shares 2032007 with normal skill-cost reduction.  The generated
    BUFF_CONF.id map must keep those semantic identities separate.
    """
    pak = PakTables(REPO_ROOT / "pak-public-kit" / "output" / "data")
    assert cls.classify_buff_primitive(20070011, pak.buff_conf) == P_POISON_MARK
    assert cls.classify_buff_primitive(20320070, pak.buff_conf) == P_MOISTURE_MARK
    assert cls.classify_buff_primitive(20320220, pak.buff_conf) == P_PASSIVE_ENERGY_REDUCE
    assert 2032007 not in cls.BASE_ID_PRIMITIVE_MAP


def test_audit_classifier_routes_heal_reversal_exact_buff():
    """Order-146 heal reversal is an exact structural BUFF_CONF row, not a whole-prefix rule."""
    pak = PakTables(REPO_ROOT / "pak-public-kit" / "output" / "data")
    assert cls.classify_buff_primitive(21460330, pak.buff_conf) == P_ANTI_HEAL


def test_audit_classifier_routes_cute_bench_cost_reduce_exact_buff():
    """Order-40 cute-stack trigger stays an exact pak buff ref in the audit axis."""
    pak = PakTables(REPO_ROOT / "pak-public-kit" / "output" / "data")
    handler = cls.classify_buff_primitive(20400130, pak.buff_conf)
    assert handler == P_CUTE_BENCH_COST_REDUCE


def test_audit_classifier_routes_only_flat_hit_count_exact_buffs():
    """Order-45 hit-count rows are exact pak refs, not a whole-order rule."""
    pak = PakTables(REPO_ROOT / "pak-public-kit" / "output" / "data")

    plus = cls.classify_buff_primitive(20450050, pak.buff_conf)
    minus = cls.classify_buff_primitive(20450090, pak.buff_conf)
    specific = cls.classify_buff_primitive(20450020, pak.buff_conf)
    assert plus == buff_ref_key(20450050)
    assert minus == buff_ref_key(20450090)
    assert specific == buff_ref_key(20450020)

    percent = cls.classify_buff_primitive(20450030, pak.buff_conf)
    assert percent == buff_ref_key(20450030)

    assert cls.classify_buff_primitive(21150010, pak.buff_conf) == ""

    drive_outcome = decode_buff_direct(21150010, pak.buff_conf)[0]
    assert isinstance(drive_outcome, EmitOutcome)
    assert drive_outcome.primitive == buff_ref_key(21150010)

    hit_outcome = decode_buff_direct(20450050, pak.buff_conf)[0]
    assert isinstance(hit_outcome, EmitOutcome)
    assert hit_outcome.primitive == buff_ref_key(20450050)
    assert hit_outcome.p0 == 0


def test_bft_multiple_num_decodes_specific_and_percent_rows():
    pak = PakTables(REPO_ROOT / "pak-public-kit" / "output" / "data")

    rows, gaps = generate_effect_rows(pak.skill_conf[7020510], pak)
    assert gaps == []
    specific = (
        buff_ref_key(20450020),
        pak_cast_moment_key(11),
        1,
        10000,
        1,
        0,
        0,
        0,
    )
    assert specific in rows
    assert _linked_tuple(specific) == (
        "op_hit_count_delta",
        11,
        1,
        10000,
        1,
        7020510,
        0,
        0,
    )

    rows, gaps = generate_effect_rows(pak.skill_conf[7020461], pak)
    assert gaps == []
    percent = (
        buff_ref_key(20450031),
        pak_cast_moment_key(6),
        1,
        10000,
        1,
        0,
        0,
        0,
    )
    assert percent in rows
    assert _linked_tuple(percent) == (
        "op_hit_count_percent_delta",
        6,
        1,
        10000,
        100,
        0,
        0,
        0,
    )


def test_equip_skill_num_decodes_damage_reduction_family():
    pak = PakTables(REPO_ROOT / "pak-public-kit" / "output" / "data")

    rows, gaps = generate_effect_rows(pak.skill_conf[200074], pak)
    assert gaps == []
    assign_raw = (buff_ref_key(20171720), pak_cast_moment_key(11), 1, 10000, 1, 0, 0, 0)
    assert rows == [assign_raw]
    linked = _linked_tuples(assign_raw, "偏振")
    assert (
        "op_entry_element_damage_reduce_by_count",
        24,
        1,
        10000,
        entry_source_code(ENTRY_SOURCE_EQUIPPED_ELEMENT, Element.NORMAL),
        1 << Element.NORMAL,
        40,
        0,
    ) in linked
    assert (
        "op_entry_element_damage_reduce_by_count",
        24,
        1,
        10000,
        entry_source_code(ENTRY_SOURCE_EQUIPPED_ELEMENT, Element.GROUND),
        1 << Element.GROUND,
        40,
        0,
    ) in linked

    rows, _gaps = generate_effect_rows(pak.skill_conf[280010], pak)
    assign_resist_raw = (buff_ref_key(20171820), pak_cast_moment_key(11), 1, 10000, 1, 0, 0, 0)
    assert assign_resist_raw in rows
    with pytest.raises(LinkGapError) as exc_info:
        link_primitive_rows(assign_resist_raw, source_name="完全偏振")
    assert exc_info.value.gap.effect_id == 1064036
    assert exc_info.value.gap.reason == "effect_shape_unsupported"

    normal_resist_raw = (effect_ref_key(1064031), pak_cast_moment_key(24), 1, 10000, 0, 0, 0, 0)
    ground_resist_raw = (effect_ref_key(1064037), pak_cast_moment_key(24), 1, 10000, 0, 0, 0, 0)
    dragon_resist_raw = (effect_ref_key(1064039), pak_cast_moment_key(24), 1, 10000, 0, 0, 0, 0)

    linked = [
        _linked_tuple(row, "完全偏振")
        for row in (normal_resist_raw, ground_resist_raw, dragon_resist_raw)
    ]
    assert (
        "op_entry_element_damage_resist_by_count",
        24,
        1,
        10000,
        entry_source_code(ENTRY_SOURCE_EQUIPPED_ELEMENT, Element.NORMAL),
        1 << Element.NORMAL,
        1,
        0,
    ) in linked
    assert (
        "op_entry_element_damage_resist_by_count",
        24,
        1,
        10000,
        entry_source_code(ENTRY_SOURCE_EQUIPPED_ELEMENT, Element.GROUND),
        1 << Element.GROUND,
        1,
        0,
    ) in linked
    assert (
        "op_entry_element_damage_resist_by_count",
        24,
        1,
        10000,
        entry_source_code(ENTRY_SOURCE_EQUIPPED_ELEMENT, Element.DRAGON),
        1 << Element.DRAGON,
        1,
        0,
    ) in linked
    assert not any(row[0] == "op_entry_element_damage_reduce_by_count" and row[-2] == 100 for row in linked)

    rows, gaps = generate_effect_rows({"skill_result": [{
        "effect_id": 1064036,
        "cast_moment": 11,
        "result_target_type": 1,
        "success_rate": 10000,
    }]}, pak)
    assert rows == [(effect_ref_key(1064036), pak_cast_moment_key(11), 1, 10000, 0, 0, 0, 0)]
    assert gaps == []
    with pytest.raises(LinkGapError):
        link_primitive_rows(rows[0], source_name="完全偏振")


def test_equip_skill_num_maps_skill_dam_type_to_engine_element_for_skill_mods():
    pak = PakTables(REPO_ROOT / "pak-public-kit" / "output" / "data")

    rows, gaps = generate_effect_rows(pak.skill_conf[200111], pak)
    assert gaps == []
    raw = (effect_ref_key(1064001), pak_cast_moment_key(11), 1, 10000, 0, 0, 0, 0)
    assert raw in rows
    assert _linked_tuple(raw, "溶解扩散") == (
        "op_entry_element_poison_stacks_by_count",
        24,
        1,
        10000,
        entry_source_code(ENTRY_SOURCE_EQUIPPED_ELEMENT, Element.POISON),
        1 << Element.WATER,
        1,
        0,
    )


def test_raw_zero_is_only_normal_through_skill_dam_type_mapping():
    skill_dam_type_common = (effect_ref_key(1064012), pak_cast_moment_key(24), 1, 10000, 0, 0, 0, 0)
    assert _linked_tuple(skill_dam_type_common, "SDT_COMMON") == (
        "op_entry_element_damage_reduce_by_count",
        24,
        1,
        10000,
        entry_source_code(ENTRY_SOURCE_EQUIPPED_ELEMENT, Element.NORMAL),
        1 << Element.NORMAL,
        40,
        0,
    )

    from roco.engine.artifacts import pak_ref_linker

    assert pak_ref_linker._element_mask((2,), "skill_dam_type") == (1 << Element.NORMAL)
    assert pak_ref_linker._element_mask((0,), "element") == 0


def test_runtime_linker_rejects_non_pak_ref_primitives():
    with pytest.raises(RuntimeError, match="only accepts effect_ref:\\* or buff_ref:\\* rows"):
        link_primitive_rows((
            P_BFT_O_T,
            pak_cast_moment_key(26),
            1,
            10000,
            2100001,
            0,
            0,
            0,
        ), source_name="地脉")


def test_bft_assign_expands_unconditional_refs_with_target_override():
    """BFT_ASSIGN remains a buff_ref in compiler and expands in engine linker."""
    pak = PakTables(REPO_ROOT / "pak-public-kit" / "output" / "data")

    rows, gaps = generate_effect_rows({"skill_result": [{
        "effect_id": 20170090,  # -> ET_HEAL_ENERGY 1019003
        "cast_moment": 12,
        "result_target_type": 1,
        "success_rate": 10000,
    }]}, pak)
    assert gaps == []
    raw = (buff_ref_key(20170090), pak_cast_moment_key(12), 1, 10000, 0, 0, 0, 0)
    assert rows == [raw]
    assert _linked_tuples(raw, "assign") == [(
        "op_heal_energy",
        12,
        1,
        10000,
        3,
        0,
        0,
        0,
    )]

    rows, gaps = generate_effect_rows({"skill_result": [{
        "effect_id": 20170830,  # -> two 星陨印记 refs, target override=2
        "cast_moment": 11,
        "result_target_type": 1,
        "success_rate": 10000,
    }]}, pak)
    assert gaps == []
    raw = (buff_ref_key(20170830), pak_cast_moment_key(11), 1, 10000, 0, 0, 0, 0)
    assert rows == [raw]
    assert _linked_tuples(raw, "assign") == [
        ("op_meteor_mark", 11, 2, 10000, 1, 0, 0, 0),
        ("op_meteor_mark", 11, 2, 10000, 1, 0, 0, 0),
    ]


def test_bft_assign_set_energy_zero_is_ability_flag_not_gap():
    pak = PakTables(REPO_ROOT / "pak-public-kit" / "output" / "data")

    table = load_ability_flags_from_effects(
        effect_conf=pak.effect_conf,
        buff_conf=pak.buff_conf,
        skill_conf=pak.skill_conf,
    )
    assert table[20170610].flag_name == AbilityFlag.START_ZERO_ENERGY.name
    assert table[1063002].flag_name == AbilityFlag.START_ZERO_ENERGY.name

    rows, gaps = generate_effect_rows(pak.skill_conf[200102], pak)
    assert gaps == []
    entry_energy = (buff_ref_key(21000010), pak_cast_moment_key(26), 1, 10000, 1, 0, 0, 0)
    start_zero = (buff_ref_key(20170610), pak_cast_moment_key(26), 1, 10000, 1, 0, 0, 0)
    assert rows == [entry_energy, start_zero]
    assert _linked_tuple(entry_energy, "地脉") == (
        "op_entry_energy_from_element_count",
        TIMING_PAK_SDT,
        1,
        10000,
        Element.GROUND.value,
        3,
        0,
        0,
    )
    with pytest.raises(LinkGapError):
        link_primitive_rows(start_zero, source_name="地脉")


def test_conditional_hit_count_buffs_link_from_pak_shape_without_desc():
    """Order-91 conditional grants are linked by pak refs, not source text."""
    pak = PakTables(REPO_ROOT / "pak-public-kit" / "output" / "data")

    rows, gaps = generate_effect_rows(pak.skill_conf[200204], pak)
    assert gaps == []
    assert rows == [(
        P_HIT_COUNT_PER_POISON_EFFECT,
        pak_cast_moment_key(11),
        1,
        10000,
        1,
        0,
        0,
        0,
    )]
    assert _linked_tuple(rows[0], "侵蚀") == (
        "op_hit_count_per_poison_effect",
        TIMING_HOOK_BEFORE_MOVE,
        1,
        10000,
        1,
        0,
        0,
        0,
    )

    rows, gaps = generate_effect_rows(pak.skill_conf[200183], pak)
    assert gaps == []
    assert rows == [(
        P_CUTE_HIT_PER_STACK,
        pak_cast_moment_key(11),
        1,
        10000,
        1,
        0,
        0,
        0,
    )]
    assert _linked_tuple(rows[0], "自由飘") == (
        "op_cute_hit_per_stack",
        TIMING_HOOK_BEFORE_MOVE,
        1,
        10000,
        1,
        0,
        0,
        0,
    )

    rows, gaps = generate_effect_rows(pak.skill_conf[7190260], pak)
    assert gaps == []
    unsupported = (buff_ref_key(20910030), pak_cast_moment_key(6), 1, 10000, 1, 0, 0, 0)
    assert unsupported in rows
    with pytest.raises(LinkGapError) as exc_info:
        link_primitive_rows(unsupported, source_name="凝望")
    assert exc_info.value.gap.reason == "buff_shape_unsupported"


def test_effect_multiple_decodes_team_same_skill_hit_count():
    pak = PakTables(REPO_ROOT / "pak-public-kit" / "output" / "data")

    rows, gaps = generate_effect_rows(pak.skill_conf[7130160], pak)

    assert gaps == []
    assert rows == [(
        effect_ref_key(1032012),
        pak_cast_moment_key(6),
        1,
        10000,
        0,
        0,
        0,
        0,
    )]


def test_slot_modifier_desc_paths_are_not_compiler_decoded():
    """Transmission/slot modifier text no longer produces compiler rows."""
    pak = PakTables(REPO_ROOT / "pak-public-kit" / "output" / "data")

    rows, gaps = generate_effect_rows(pak.skill_conf[7070160], pak)
    assert rows == [(P_SLOT_SKILL_MOD_EFFECT, pak_cast_moment_key(11), 1, 10000, 0, 0, 0, 0)]
    assert gaps == []
    with pytest.raises(LinkGapError) as exc_info:
        link_primitive_rows(rows[0], source_name="磁暴")
    assert exc_info.value.gap.reason == "effect_shape_unsupported"

    rows, gaps = generate_effect_rows(pak.skill_conf[7070030], pak)
    assert rows == [(P_SLOT_SKILL_MOD_BUFF, pak_cast_moment_key(11), 1, 10000, 1, 0, 0, 0)]
    assert gaps == []
    with pytest.raises(LinkGapError) as exc_info:
        link_primitive_rows(rows[0], source_name="传动")
    assert exc_info.value.gap.reason == "buff_shape_unsupported"

    rows, gaps = generate_effect_rows(pak.skill_conf[7070170], pak)
    assert (P_SLOT_SKILL_MOD_BUFF, pak_cast_moment_key(11), 1, 10000, 1, 0, 0, 0) in rows
    assert gaps == []


def test_bft_assign_keeps_condition_and_nested_flag_as_gaps():
    pak = PakTables(REPO_ROOT / "pak-public-kit" / "output" / "data")

    rows, gaps = generate_effect_rows({"skill_result": [{
        "effect_id": 20170210,  # target/condition code 299909
        "cast_moment": 11,
        "result_target_type": 1,
        "success_rate": 10000,
    }]}, pak)
    assert rows == [(buff_ref_key(20170210), pak_cast_moment_key(11), 1, 10000, 0, 0, 0, 0)]
    assert gaps == []
    with pytest.raises(LinkGapError) as exc_info:
        link_primitive_rows(rows[0], source_name="石天平")
    assert exc_info.value.gap.reason == "assign_condition_unsupported"

    rows, gaps = generate_effect_rows({"skill_result": [{
        "effect_id": 20170290,  # -> AbilityFlagRule 1066001 via BFT_ASSIGN
        "cast_moment": 11,
        "result_target_type": 1,
        "success_rate": 10000,
    }]}, pak)
    assert rows == [(buff_ref_key(20170290), pak_cast_moment_key(11), 1, 10000, 0, 0, 0, 0)]
    assert gaps == []
    with pytest.raises(LinkGapError) as exc_info:
        link_primitive_rows(rows[0], source_name="循环")
    assert exc_info.value.gap.reason == "effect_shape_unsupported"
    assert exc_info.value.gap.effect_id == 1066001


def test_audit_classifier_uses_prefix_axis_for_mixed(buffbase_conf):
    """Dominant base_ids in mixed prefixes (e.g. 2011's order=11 group)
    have NO buffbase_order entry, so the audit map uses the mixed prefix
    layer and resolves via PREFIX_PRIMITIVE_MAP[2011]."""
    # Find a 2011 base_id with order==11 (the dominant order, which is
    # NOT in the seed because 2011 is the mixed prefix).
    target_bid = next(
        bid for bid, rec in buffbase_conf.items()
        if bid // 1000 == 2011 and int(rec.get("buffbase_order", 0)) == 11
    )
    assert target_bid not in cls.BASE_ID_VIA_ORDER_MAP
    buff_conf_stub = {99999999: {"buff_base_ids": [target_bid]}}
    h = cls.classify_buff_primitive(99999999, buff_conf_stub)
    assert h == P_DAMAGE_REDUCTION
    assert 2011 in cls.PREFIX_PRIMITIVE_MAP


def test_audit_classifier_outlier_routes_to_via_order_handler(buffbase_conf):
    """Outliers in mixed prefixes (e.g. base_id 2050011 with order=48)
    now resolve via the buffbase_order axis to BFT_PET_TRANSE, fixing
    a pre-7C silent miscompile where prefix 2050 was returning
    BFT_ATTR_CHANGE for a force-switch primitive.
    """
    # base_id 2050011: editor_name='闪电步吹飞自己', buffbase_order=48
    target_bid = 2050011
    assert target_bid in cls.BASE_ID_VIA_ORDER_MAP
    buff_conf_stub = {99999999: {"buff_base_ids": [target_bid]}}
    h = cls.classify_buff_primitive(99999999, buff_conf_stub)
    assert h == P_FORCE_SWITCH


def test_immunity_desc_buff_maps_to_active_immunity_primitive():
    pak = PakTables(REPO_ROOT / "pak-public-kit" / "output" / "data")
    rows, gaps = generate_effect_rows({"skill_result": [{
        "effect_id": 20030010,
        "cast_moment": 11,
        "result_target_type": 1,
        "success_rate": 10000,
    }]}, pak)
    assert gaps == []
    assert rows == [(
        P_ACTIVE_IMMUNITY_BUFF,
        "battle_event:BEVT_BEFORE_HURT",
        1,
        10000,
        0,
        0,
        0,
        0,
    )]
    assert _linked_tuple(rows[0], "免疫") == (
        "op_apply_active_buff",
        11,
        1,
        10000,
        20030010,
        13,
        999,
        0,
    )


def test_zero_energy_bft_immune_shape_links_from_pak_shape():
    pak = PakTables(REPO_ROOT / "pak-public-kit" / "output" / "data")
    rows, gaps = generate_effect_rows({"skill_result": [{
        "effect_id": 20030220,
        "cast_moment": 11,
        "result_target_type": 1,
        "success_rate": 10000,
    }]}, pak)
    assert gaps == []
    assert rows == [(
        buff_ref_key(20030220),
        "battle_event:BEVT_BEFORE_HURT",
        1,
        10000,
        0,
        0,
        0,
        0,
    )]
    assert _linked_tuple(rows[0], "零能量切换") == (
        "op_auto_switch_on_zero_energy",
        11,
        1,
        10000,
        0,
        0,
        0,
        0,
    )
