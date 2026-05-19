"""Tests for pak-native effect code generation."""

import json
from pathlib import Path

import pytest

from roco.compiler.effect_model import PakOp, Timing
from roco.compiler.effect_codegen import (
    PakTables,
    generate_effect_rows,
    build_ability_effect_rows,
    report_coverage,
    H_DAMAGE, H_STAT_BUFF, H_POISON, H_NOOP,
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


def test_pak_op_has_major_families():
    assert PakOp.STAT_MOD == 2001
    assert PakOp.IMMUNITY_LOCK == 2003
    assert PakOp.POWER_MOD == 2023
    assert PakOp.EFF_DAMAGE == 10002
    assert PakOp.EFF_STATE_CHANGE == 10003
    assert PakOp.UNSUPPORTED == 0


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
    rows = generate_effect_rows(skill_row, pak)
    assert len(rows) >= 1
    assert rows[0][0] == H_STAT_BUFF


def test_generate_effect_rows_damage_ref(pak):
    skill_row = {"skill_result": [{
        "effect_id": 1001001,
        "cast_moment": 6,
        "result_target_type": 2,
        "success_rate": 10000,
    }]}
    rows = generate_effect_rows(skill_row, pak)
    assert len(rows) >= 1
    assert rows[0][0] == H_DAMAGE


def test_generate_effect_rows_state_change_ref(pak):
    skill_row = {"skill_result": [{
        "effect_id": 1004001,
        "cast_moment": 11,
        "result_target_type": 1,
        "success_rate": 10000,
    }]}
    rows = generate_effect_rows(skill_row, pak)
    # type=3 (state change) defaults to NOOP — specific cases handled via overrides
    assert len(rows) == 0


def test_generate_effect_rows_timing_from_cast_moment(pak):
    skill_row = {"skill_result": [{
        "effect_id": 20010010,
        "cast_moment": 12,
        "result_target_type": 1,
        "success_rate": 10000,
    }]}
    rows = generate_effect_rows(skill_row, pak)
    assert rows[0][1] == Timing.TURN_END


def test_generate_effect_rows_empty_skill_result(pak):
    rows = generate_effect_rows({"skill_result": []}, pak)
    assert rows == []
    rows2 = generate_effect_rows({}, pak)
    assert rows2 == []


def test_build_ability_effect_rows(pak):
    ability_row = {"skill_result": [{
        "effect_id": 20070010,
        "cast_moment": 11,
        "result_target_type": 2,
        "success_rate": 5000,
    }]}
    rows = build_ability_effect_rows(ability_row, pak)
    assert len(rows) >= 1
    assert rows[0][0] == H_POISON


def test_report_coverage(pak):
    cov = report_coverage(pak)
    assert "total" in cov
    assert "mapped" in cov
    assert "coverage_pct" in cov
    assert isinstance(cov["coverage_pct"], float)
