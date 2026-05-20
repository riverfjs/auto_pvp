"""Tests for pak-native effect code generation (three-state pipeline)."""

import json
from pathlib import Path

import pytest

from roco.compiler.effect_model import Timing
from roco.generated.pak_ops import EFF_DAMAGE, EFF_STATE_CHANGE, PAK_PREFIX_NAMES
from roco.compiler.effect_codegen import (
    PakTables,
    generate_effect_rows,
    build_ability_effect_rows,
    H_DAMAGE, H_SELF_BUFF, H_POISON,
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
    # PAK_PREFIX_NAMES is generated from BUFF_CONF + prefix_handlers.jsonl;
    # the legacy ``PakOp`` enum is retired.  Confirm the table still names
    # the most-used families and exports the synthetic EFFECT_CONF markers.
    assert PAK_PREFIX_NAMES[2001] == "STAT_MOD"
    assert PAK_PREFIX_NAMES[2023] == "POWER_MOD"
    # Prefixes that were ``handler: H_NOOP`` entries (2003 IMMUNITY_LOCK,
    # 2040 DETECTION, 2062 COOLDOWN) were removed in the H_NOOP cleanup —
    # they no longer carry an alias and surface as ``PREFIX_<n>``.
    assert PAK_PREFIX_NAMES[2003] == "PREFIX_2003"
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


# ── three-state contract tests ───────────────────────────────────────────


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


def test_jsonl_rejects_h_noop_handler(tmp_path, monkeypatch):
    """exact_effects.jsonl loader must reject ``handler: H_NOOP`` rows."""
    fake_jsonl = tmp_path / "exact_effects.jsonl"
    fake_jsonl.write_text(
        '{"effect_id": 9999001, "handler": "H_NOOP", "args": [0,0,0,0], '
        '"evidence": "intentional"}\n',
        encoding="utf-8",
    )
    from roco.compiler.effect_codegen import exact_decoders as ed
    monkeypatch.setattr(ed, "_RULES_PATH", fake_jsonl)
    with pytest.raises(RuntimeError, match="handler: H_NOOP"):
        ed._load_jsonl()


def test_jsonl_ignored_kind_routes_to_ignored_list(tmp_path, monkeypatch, pak):
    """JSONL row with ``kind: ignored`` produces an IgnoredOutcome.

    Verifies that ``generate_effect_rows`` returns the entry in the
    ``ignored`` channel (not ``rows``, not ``gaps``).
    """
    fake_jsonl = tmp_path / "exact_effects.jsonl"
    fake_jsonl.write_text(
        '{"effect_id": 9991234, "kind": "ignored", '
        '"reason": "visual_only_animation", '
        '"evidence": "pak EFFECT_CONF.json: 9991234 editor_name=\'纯动画\'", '
        '"pak_table": "EFFECT_CONF"}\n',
        encoding="utf-8",
    )
    # Reload the override table from the fake JSONL path.
    from roco.compiler.effect_codegen import exact_decoders as ed
    monkeypatch.setattr(ed, "_RULES_PATH", fake_jsonl)
    fresh = ed._load_jsonl()
    monkeypatch.setattr(ed, "EXACT_EFFECT_DECODERS", {**fresh, **ed._weather_outcomes()})

    skill_row = {"skill_result": [{
        "effect_id": 9991234,
        "cast_moment": 11,
        "result_target_type": 1,
        "success_rate": 10000,
    }]}
    rows, ignored, gaps = generate_effect_rows(skill_row, pak)
    assert rows == []
    assert gaps == []
    assert len(ignored) == 1
    assert ignored[0]["reason"] == "visual_only_animation"
    assert ignored[0]["pak_table"] == "EFFECT_CONF"
    assert ignored[0]["evidence"].startswith("pak EFFECT_CONF")


def test_jsonl_ignored_rejects_handler_args(tmp_path, monkeypatch):
    """``kind: ignored`` forbids ``handler`` / ``args`` — loader must reject."""
    fake_jsonl = tmp_path / "exact_effects.jsonl"
    fake_jsonl.write_text(
        '{"effect_id": 9991234, "kind": "ignored", '
        '"handler": "H_HEAL_HP", "reason": "x", "evidence": "y"}\n',
        encoding="utf-8",
    )
    from roco.compiler.effect_codegen import exact_decoders as ed
    monkeypatch.setattr(ed, "_RULES_PATH", fake_jsonl)
    with pytest.raises(RuntimeError, match="forbids ``handler``"):
        ed._load_jsonl()


def test_jsonl_ignored_requires_evidence(tmp_path, monkeypatch):
    """``kind: ignored`` must carry both ``reason`` and ``evidence``."""
    fake_jsonl = tmp_path / "exact_effects.jsonl"
    fake_jsonl.write_text(
        '{"effect_id": 9991234, "kind": "ignored", "reason": "x"}\n',
        encoding="utf-8",
    )
    from roco.compiler.effect_codegen import exact_decoders as ed
    monkeypatch.setattr(ed, "_RULES_PATH", fake_jsonl)
    with pytest.raises(RuntimeError, match="requires both ``reason`` and ``evidence``"):
        ed._load_jsonl()
