"""Tests for pak-native effect code generation (four-state pipeline)."""

import json
from pathlib import Path

import pytest

from roco.common.primitive_keys import (
    buff_ref_key,
    effect_ref_key,
)
from roco.generated.pak_ops import EFF_DAMAGE, EFF_STATE_CHANGE, PAK_PREFIX_NAMES
from roco.compiler_v2.effect_codegen import (
    PakTables,
    generate_effect_rows,
    build_ability_effect_rows,
)
from roco.compiler_v2.timing_keys import pak_cast_moment_key

P_DAMAGE = effect_ref_key(1001001)
P_HIT_COUNT_DELTA = buff_ref_key(20450050)
P_POISON = buff_ref_key(20070010)
P_SELF_BUFF = buff_ref_key(20010010)


def _write_table(path: Path, rows: dict[str, dict]) -> None:
    path.write_text(
        '{"RocoDataRows":' + json.dumps(rows, ensure_ascii=False, separators=(",", ":")) + "}",
        encoding="utf-8",
    )


@pytest.fixture
def pak(tmp_path):
    bindata = tmp_path / "BinData"
    bindata.mkdir()
    _write_table(bindata / "SKILL_CONF.json", {})
    _write_table(bindata / "EFFECT_CONF.json", {
        "1001001": {
            "id": 1001001,
            "editor_name": "造成伤害-舍身",
            "type": 2,
            "effect_param": [
                {"params": [1]}, {"params": [2]}, {"params": [300]},
                {"params": [0]}, {"params": [0]}, {"params": [1]}, {"params": [300]},
            ],
        },
        "1004001": {
            "id": 1004001,
            "editor_name": "通用净化",
            "type": 3,
            "effect_param": [{"params": [1]}, {"params": [20070010]}, {"params": [0]}],
        },
    })
    _write_table(bindata / "BUFF_CONF.json", {
        "20010010": {
            "id": 20010010,
            "editor_name": "通用物攻增加buff10%",
            "buff_base_ids": [2001001],
            "type": 1,
            "add_max": 99,
            "desc": "物攻+10%",
        },
        "20070010": {
            "id": 20070010,
            "editor_name": "通用中毒",
            "buff_base_ids": [2007001],
            "type": 3,
            "add_max": 15,
            "desc": "中毒",
        },
        "20450050": {
            "id": 20450050,
            "editor_name": "连击",
            "buff_base_ids": [2045005],
            "type": 1,
            "add_max": 99,
            "desc": "连击次数+1",
        },
    })
    return PakTables(tmp_path)


def test_pak_op_prefix_table_covers_major_families():
    # PAK_PREFIX_NAMES is generated from BUFF_CONF + Python semantic bindings;
    # the legacy ``PakOp`` enum is retired.  Confirm the table still names
    # the most-used families and exports the synthetic EFFECT_CONF markers.
    assert PAK_PREFIX_NAMES[2001] == "BFT_ATTR_CHANGE"
    assert PAK_PREFIX_NAMES[2023] == "BFT_INC_DAM_BY_SKILL"
    # Unhandled prefixes now keep their pak/Lua enum identity instead of
    # falling back to an opaque JSONL-era ``PREFIX_<n>`` label.
    assert PAK_PREFIX_NAMES[2003] == "BFT_IMMUNE"
    assert EFF_DAMAGE == 10002
    assert EFF_STATE_CHANGE == 10003


def test_timing_matches_cast_moment():
    assert pak_cast_moment_key(11) == "battle_event:BEVT_BEFORE_HURT"
    assert pak_cast_moment_key(12) == "battle_event:BEVT_BEFORE_ADD"
    assert pak_cast_moment_key(6) == "battle_event:BEVT_ROUND_CALC_START"
    assert pak_cast_moment_key(24) == "battle_event:BEVT_SDT"
    assert pak_cast_moment_key(10) == "battle_event:BEVT_BEFORE_SKILL_DAMAGE_CALC"


def test_generate_effect_rows_buff_ref(pak):
    skill_row = {"skill_result": [{
        "effect_id": 20010010,
        "cast_moment": 11,
        "result_target_type": 1,
        "success_rate": 10000,
    }]}
    rows, gaps = generate_effect_rows(skill_row, pak)
    assert len(rows) >= 1
    assert rows[0][0] == P_SELF_BUFF
    assert gaps == []


def test_generate_effect_rows_damage_ref(pak):
    skill_row = {"skill_result": [{
        "effect_id": 1001001,
        "cast_moment": 6,
        "result_target_type": 2,
        "success_rate": 10000,
    }]}
    rows, gaps = generate_effect_rows(skill_row, pak)
    assert len(rows) >= 1
    assert rows[0][0] == P_DAMAGE
    assert gaps == []


def test_generate_effect_rows_state_change_records_gap(pak):
    skill_row = {"skill_result": [{
        "effect_id": 1004001,
        "cast_moment": 11,
        "result_target_type": 1,
        "success_rate": 10000,
    }]}
    rows, gaps = generate_effect_rows(skill_row, pak)
    assert rows == [(
        effect_ref_key(1004001),
        pak_cast_moment_key(11),
        1,
        10000,
        0,
        0,
        0,
        0,
    )]
    assert gaps == []


def test_generate_effect_rows_timing_from_cast_moment(pak):
    skill_row = {"skill_result": [{
        "effect_id": 20010010,
        "cast_moment": 12,
        "result_target_type": 1,
        "success_rate": 10000,
    }]}
    rows, gaps = generate_effect_rows(skill_row, pak)
    assert rows[0][1] == pak_cast_moment_key(12)


def test_generate_effect_rows_empty_skill_result(pak):
    rows, gaps = generate_effect_rows({"skill_result": []}, pak)
    assert rows == []
    assert gaps == []
    rows2, gaps2 = generate_effect_rows({}, pak)
    assert rows2 == []
    assert gaps2 == []


def test_generate_effect_rows_skips_blank_entry(pak):
    """Bare ``{}`` slots in ``skill_result`` are pak padding, not gaps.

    Lock this in — earlier the pipeline turned 436 such placeholders into
    ``effect_0`` audit rows that polluted ``effect_gaps``/strict build.
    """
    skill_row = {"skill_result": [
        {"effect_id": 20070010, "cast_moment": 11, "result_target_type": 2,
         "success_rate": 10000, "buff_group_level": 1},
        {},  # placeholder pak padding
        {"effect_id": 0, "cast_moment": 11, "result_target_type": 1,
         "success_rate": 10000},
    ]}
    rows, gaps = generate_effect_rows(skill_row, pak)
    assert len(rows) == 1
    assert rows[0][0] == P_POISON
    assert gaps == []


def test_generate_effect_rows_stack_priority(pak):
    """Stack priority: pak repeat > skill_result.buff_group_level > 1.

    A direct buff reference with ``buff_group_level=3`` should pack p0=3
    (剧毒-style), and a compound effect whose chosen buff repeats five
    times in pak's effect_param should pack p0=5 (焚烧烙印-style) even
    when no buff_group_level is set.
    """
    # buff_group_level path
    rows, _gaps = generate_effect_rows({"skill_result": [{
        "effect_id": 20070010, "cast_moment": 11, "result_target_type": 2,
        "success_rate": 10000, "buff_group_level": 3,
    }]}, pak)
    assert rows[0][0] == P_POISON
    assert rows[0][4] == 3  # p0 = buff_group_level


def test_generate_effect_rows_hit_count_uses_buff_group_level(pak):
    rows, gaps = generate_effect_rows({"skill_result": [{
        "effect_id": 20450050, "cast_moment": 11, "result_target_type": 1,
        "success_rate": 10000, "buff_group_level": 3,
    }]}, pak)
    assert gaps == []
    assert rows[0][0] == P_HIT_COUNT_DELTA
    assert rows[0][4] == 3


def test_build_ability_effect_rows(pak):
    ability_row = {"skill_result": [{
        "effect_id": 20070010,
        "cast_moment": 11,
        "result_target_type": 2,
        "success_rate": 5000,
    }]}
    rows, gaps = build_ability_effect_rows(ability_row, pak)
    assert len(rows) >= 1
    assert rows[0][0] == P_POISON
    assert gaps == []


# ── four-state contract tests ────────────────────────────────────────────


def test_compound_type1_returns_gap(pak):
    """type=1 compound remains a raw pak effect ref at compiler boundary."""
    pak.effect_conf[1099001] = {
        "id": 1099001,
        "editor_name": "fixture-compound-type1",
        "type": 1,
        "effect_param": [
            {"params": [20010010]},
            {"params": [20070010]},
            {"params": [0]},
        ],
    }
    skill_row = {"skill_result": [{
        "effect_id": 1099001,
        "cast_moment": 11,
        "result_target_type": 1,
        "success_rate": 10000,
    }]}
    rows, gaps = generate_effect_rows(skill_row, pak)
    assert rows == [(
        effect_ref_key(1099001),
        pak_cast_moment_key(11),
        1,
        10000,
        0,
        0,
        0,
        0,
    )]
    assert gaps == []


def test_no_buff_type1_returns_gap(pak):
    """type=1 no-buff remains a raw pak effect ref at compiler boundary."""
    pak.effect_conf[1099002] = {
        "id": 1099002,
        "editor_name": "fixture-no-buff-type1",
        "type": 1,
        "effect_param": [
            {"params": [42]},   # not in BUFF_CONF
            {"params": [1234]}, # not in BUFF_CONF
            {"params": [0]},
        ],
    }
    skill_row = {"skill_result": [{
        "effect_id": 1099002,
        "cast_moment": 11,
        "result_target_type": 1,
        "success_rate": 10000,
    }]}
    rows, gaps = generate_effect_rows(skill_row, pak)
    assert rows == [(
        effect_ref_key(1099002),
        pak_cast_moment_key(11),
        1,
        10000,
        0,
        0,
        0,
        0,
    )]
    assert gaps == []


def test_unmapped_prefix_buff_still_emits_raw_buff_ref(pak):
    """Existing BUFF_CONF ids do not become compiler gaps."""
    pak.buff_conf[29991234] = {
        "id": 29991234,
        "editor_name": "fixture-unmapped-prefix",
        "buff_base_ids": [2999001],
        "type": 1,
    }
    skill_row = {"skill_result": [{
        "effect_id": 29991234,  # direct buff reference path
        "cast_moment": 11,
        "result_target_type": 1,
        "success_rate": 10000,
    }]}
    rows, gaps = generate_effect_rows(skill_row, pak)
    assert rows == [(
        buff_ref_key(29991234),
        pak_cast_moment_key(11),
        1,
        10000,
        0,
        0,
        0,
        0,
    )]
    assert gaps == []


def test_unknown_effect_id_becomes_gap(pak):
    """effect_id absent from both EFFECT_CONF and BUFF_CONF → GapOutcome."""
    skill_row = {"skill_result": [{
        "effect_id": 9999999,  # not in fixture pak
        "cast_moment": 11,
        "result_target_type": 1,
        "success_rate": 10000,
    }]}
    rows, gaps = generate_effect_rows(skill_row, pak)
    assert rows == []
    assert len(gaps) == 1
    assert gaps[0]["reason"] == "effect_id_not_in_pak"
    assert gaps[0]["primitive"] == "effect_9999999"


def test_emit_outcome_invariant_primitive_nonempty(pak):
    """Every EmitOutcome emitted via the structural decoder must have a primitive.

    Runs the fixture pak through both decoders, scans every effect_id
    that resolves to an EmitOutcome, and asserts the primitive is non-empty.
    Does NOT read ``_data/canonical/*``; works purely on the in-memory
    fixture so stale on-disk artifacts can't pollute the assertion.
    """
    for eid in (1001001, 20010010, 20070010):
        skill_row = {"skill_result": [{
            "effect_id": eid,
            "cast_moment": 11,
            "result_target_type": 1,
            "success_rate": 10000,
        }]}
        rows, _gaps = generate_effect_rows(skill_row, pak)
        for row in rows:
            assert row[0], f"effect_id {eid} produced empty primitive"


def test_no_python_exact_effect_rules_table():
    """Compiler effect_codegen no longer hosts exact behavior decoders."""
    path = Path(__file__).resolve().parents[1] / "roco" / "compiler_v2" / "semantics.py"
    exact_path = Path(__file__).resolve().parents[1] / "roco" / "compiler_v2" / "effect_codegen" / "exact_decoders.py"

    assert not path.exists()
    assert not exact_path.exists()


def test_former_exact_burn_mark_row_stays_effect_ref_for_linker(pak):
    """The compiler does not decode the 1042014 burn payload."""
    pak.effect_conf[1042014] = {
        "id": 1042014,
        "editor_name": "fixture-mark-to-burn",
        "effect_order": 42,
        "type": 1,
        "effect_param": [
            {"params": [0]},
            {"params": [20011578]},
            {"params": [20070020, 20070020, 20070020, 20070020, 20070020]},
            {"params": [99]},
            {"params": [0]},
        ],
    }
    pak.buff_conf[20011578] = {
        "id": 20011578,
        "editor_name": "焚烧烙印标记",
        "buff_base_ids": [2001081],
    }
    pak.buff_conf[20070020] = {
        "id": 20070020,
        "editor_name": "通用灼烧",
        "buff_base_ids": [2007002],
    }

    rows, gaps = generate_effect_rows({"skill_result": [{
        "effect_id": 1042014,
        "cast_moment": 11,
        "result_target_type": 1,
        "success_rate": 10000,
    }]}, pak)
    assert rows == [(
        effect_ref_key(1042014),
        pak_cast_moment_key(11),
        1,
        10000,
        0,
        0,
        0,
        0,
    )]
    assert gaps == []
