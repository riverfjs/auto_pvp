"""Tests for pak-native effect code generation (four-state pipeline)."""

import json
from pathlib import Path

import pytest

from roco.compiler_v2.effect_model import Timing
from roco.generated.pak_ops import EFF_DAMAGE, EFF_STATE_CHANGE, PAK_PREFIX_NAMES
from roco.compiler_v2.effect_codegen import (
    PakTables,
    generate_effect_rows,
    build_ability_effect_rows,
    H_DAMAGE, H_DISPEL_MARKS_TO_BURN, H_HEAL_HP, H_SELF_BUFF, H_POISON,
)


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
    })
    return PakTables(tmp_path)


def test_pak_op_prefix_table_covers_major_families():
    # PAK_PREFIX_NAMES is generated from BUFF_CONF + Python semantic bindings;
    # the legacy ``PakOp`` enum is retired.  Confirm the table still names
    # the most-used families and exports the synthetic EFFECT_CONF markers.
    assert PAK_PREFIX_NAMES[2001] == "STAT_MOD"
    assert PAK_PREFIX_NAMES[2023] == "POWER_MOD"
    # Unhandled prefixes now keep their pak/Lua enum identity instead of
    # falling back to an opaque JSONL-era ``PREFIX_<n>`` label.
    assert PAK_PREFIX_NAMES[2003] == "BFT_IMMUNE"
    assert EFF_DAMAGE == 10002
    assert EFF_STATE_CHANGE == 10003


def test_timing_matches_cast_moment():
    assert Timing.AFTER_MOVE == 11
    assert Timing.TURN_END == 12
    assert Timing.CALC_DAMAGE == 6
    assert Timing.SWITCH_IN == 24
    assert Timing.TURN_START == 10


def test_generate_effect_rows_buff_ref(pak):
    skill_row = {"skill_result": [{
        "effect_id": 20010010,
        "cast_moment": 11,
        "result_target_type": 1,
        "success_rate": 10000,
    }]}
    rows, ignored, gaps = generate_effect_rows(skill_row, pak)
    assert len(rows) >= 1
    assert rows[0][0] == H_SELF_BUFF
    assert ignored == []
    assert gaps == []


def test_generate_effect_rows_damage_ref(pak):
    skill_row = {"skill_result": [{
        "effect_id": 1001001,
        "cast_moment": 6,
        "result_target_type": 2,
        "success_rate": 10000,
    }]}
    rows, ignored, gaps = generate_effect_rows(skill_row, pak)
    assert len(rows) >= 1
    assert rows[0][0] == H_DAMAGE
    assert ignored == []
    assert gaps == []


def test_generate_effect_rows_state_change_records_gap(pak):
    skill_row = {"skill_result": [{
        "effect_id": 1004001,
        "cast_moment": 11,
        "result_target_type": 1,
        "success_rate": 10000,
    }]}
    rows, ignored, gaps = generate_effect_rows(skill_row, pak)
    # type=3 state changes are not yet executable — must surface as audit gaps.
    assert rows == []
    assert ignored == []
    assert len(gaps) == 1
    assert gaps[0]["reason"].startswith("effect_type_3")
    assert gaps[0]["params"]["effect_id"] == 1004001


def test_generate_effect_rows_timing_from_cast_moment(pak):
    skill_row = {"skill_result": [{
        "effect_id": 20010010,
        "cast_moment": 12,
        "result_target_type": 1,
        "success_rate": 10000,
    }]}
    rows, ignored, gaps = generate_effect_rows(skill_row, pak)
    assert rows[0][1] == Timing.TURN_END


def test_generate_effect_rows_empty_skill_result(pak):
    rows, ignored, gaps = generate_effect_rows({"skill_result": []}, pak)
    assert rows == []
    assert ignored == []
    assert gaps == []
    rows2, ignored2, gaps2 = generate_effect_rows({}, pak)
    assert rows2 == []
    assert ignored2 == []
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
    rows, ignored, gaps = generate_effect_rows(skill_row, pak)
    assert len(rows) == 1
    assert rows[0][0] == H_POISON
    assert ignored == []
    assert gaps == []


def test_generate_effect_rows_stack_priority(pak):
    """Stack priority: pak repeat > skill_result.buff_group_level > 1.

    A direct buff reference with ``buff_group_level=3`` should pack p0=3
    (剧毒-style), and a compound effect whose chosen buff repeats five
    times in pak's effect_param should pack p0=5 (焚烧烙印-style) even
    when no buff_group_level is set.
    """
    # buff_group_level path
    rows, _ignored, _gaps = generate_effect_rows({"skill_result": [{
        "effect_id": 20070010, "cast_moment": 11, "result_target_type": 2,
        "success_rate": 10000, "buff_group_level": 3,
    }]}, pak)
    assert rows[0][0] == H_POISON
    assert rows[0][4] == 3  # p0 = buff_group_level


def test_build_ability_effect_rows(pak):
    ability_row = {"skill_result": [{
        "effect_id": 20070010,
        "cast_moment": 11,
        "result_target_type": 2,
        "success_rate": 5000,
    }]}
    rows, ignored, gaps = build_ability_effect_rows(ability_row, pak)
    assert len(rows) >= 1
    assert rows[0][0] == H_POISON
    assert ignored == []
    assert gaps == []


# ── four-state contract tests ────────────────────────────────────────────


def test_compound_type1_returns_gap(pak):
    """type=1 effect with multiple BUFF_CONF candidates → GapOutcome.

    Direct decoder coverage: until the new compound type was tested only
    via exact_decoders override.  Inject an EFFECT_CONF row that names
    both fixture buffs (20010010 STAT_MOD + 20070010 POISON) in its
    ``effect_param`` and assert classify produces ``effect_type_1_compound``.
    """
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
    rows, ignored, gaps = generate_effect_rows(skill_row, pak)
    assert rows == []
    assert ignored == []
    assert len(gaps) == 1
    assert gaps[0]["reason"] == "effect_type_1_compound"
    assert gaps[0]["primitive"] == "effect_1099001"


def test_no_buff_type1_returns_gap(pak):
    """type=1 effect with zero BUFF_CONF candidates → GapOutcome.

    Inject an EFFECT_CONF row whose effect_param contains only ints that
    are NOT BUFF_CONF ids.  classify must return
    ``effect_type_1_no_buff`` and emit no row.
    """
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
    rows, ignored, gaps = generate_effect_rows(skill_row, pak)
    assert rows == []
    assert ignored == []
    assert len(gaps) == 1
    assert gaps[0]["reason"] == "effect_type_1_no_buff"
    assert gaps[0]["primitive"] == "effect_1099002"


def test_unmapped_prefix_buff_reports_prefix_gap(pak, monkeypatch):
    """A buff whose base_id prefix has no handler must surface as
    ``prefix_<n>_unmapped`` — not ``buff_unclassified``.

    Locks in the fix for the regression where dropping
    ``handler: H_NOOP`` rows in old prefix semantics left zero
    values in ``prefix_handler_map.json``; ``buff_<n>`` reason was
    misclassifying buffs as ``buff_unclassified`` instead.
    """
    from roco.compiler_v2.effect_codegen import classify

    # Inject an extra buff whose base_id prefix (2999) is guaranteed
    # absent from the prefix map.  Use monkeypatch so we don't have to
    # rewrite the fixture tables on disk.
    pak.buff_conf[29991234] = {
        "id": 29991234,
        "editor_name": "fixture-unmapped-prefix",
        "buff_base_ids": [2999001],
        "type": 1,
    }
    monkeypatch.setitem(classify.PREFIX_HANDLER_MAP, 2999, 0)  # ensure not mapped
    classify.PREFIX_HANDLER_MAP.pop(2999, None)

    skill_row = {"skill_result": [{
        "effect_id": 29991234,  # direct buff reference path
        "cast_moment": 11,
        "result_target_type": 1,
        "success_rate": 10000,
    }]}
    rows, ignored, gaps = generate_effect_rows(skill_row, pak)
    assert rows == []
    assert ignored == []
    assert len(gaps) == 1
    assert gaps[0]["reason"] == "prefix_2999_unmapped"
    assert gaps[0]["primitive"] == "prefix_2999"


def test_unknown_effect_id_becomes_gap(pak):
    """effect_id absent from both EFFECT_CONF and BUFF_CONF → GapOutcome."""
    skill_row = {"skill_result": [{
        "effect_id": 9999999,  # not in fixture pak
        "cast_moment": 11,
        "result_target_type": 1,
        "success_rate": 10000,
    }]}
    rows, ignored, gaps = generate_effect_rows(skill_row, pak)
    assert rows == []
    assert ignored == []
    assert len(gaps) == 1
    assert gaps[0]["reason"] == "effect_id_not_in_pak"
    assert gaps[0]["primitive"] == "effect_9999999"


def test_emit_outcome_invariant_handler_idx_positive(pak):
    """Every EmitOutcome emitted via the structural decoder must have handler_idx > 0.

    Runs the fixture pak through both decoders, scans every effect_id
    that resolves to an EmitOutcome, and asserts ``handler_idx > 0``.
    Catches regressions where a decoder silently emits H_NOOP=0 again.
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
        rows, _ignored, _gaps = generate_effect_rows(skill_row, pak)
        for row in rows:
            assert row[0] > 0, f"effect_id {eid} produced tag_code={row[0]} (H_NOOP not allowed)"


def test_no_python_exact_effect_rules_table():
    """Runtime exact effects are now generated/weather-only, not Python rows."""
    from roco.compiler_v2.effect_codegen import exact_decoders as ed

    path = Path(__file__).resolve().parents[1] / "roco" / "compiler_v2" / "semantics.py"

    assert not hasattr(ed, "_load_python_rules")
    assert not path.exists()


def test_former_exact_burn_mark_row_uses_family_decoder(pak):
    """The 1042014 burn payload is derived from pak shape, not id semantics."""
    from roco.compiler_v2.effect_codegen.family_axes import decode_family_axes

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

    entry = decode_family_axes(1042014, pak.effect_conf, pak.buff_conf)
    assert entry is not None
    assert entry.handler_idx == H_DISPEL_MARKS_TO_BURN
    assert entry.p0 == 5
