"""Phase 5C-iii: ABILITY_FLAGS codegen / loader / classifier tests.

Covers the four hard boundaries:

1. **ability-only gate** — :func:`generate_effect_rows` with
   ``allow_ability_flags=False`` rejects an :class:`AbilityFlagOutcome`
   (skill path must not silently swallow ability-passive effect_ids).
2. **multiplier reject** — loader rejects ``effect_param[1] != [1]``
   (and the shape variants around it).  No defaulting / truncation.
3. **ABILITY_FLAGS = ability_effect_ids ⨝ rules JSONL** — codegen
   populates the per-ability mask only from the new SQLite table joined
   with the loaded rules; canonical jsonl is not read at codegen time.

(End-to-end residual heal — boundary 4 — lives in
``tests/test_status_damage_heal.py``.)
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from roco.common.enums import AbilityFlag
from roco.compiler.codegen import ability_flags_codegen
from roco.compiler.effect_codegen import (
    AbilityFlagOutcome,
    EmitOutcome,
    GapOutcome,
    IgnoredOutcome,
    PakTables,
    generate_effect_rows,
)
from roco.compiler.effect_codegen.ability_flags_from_effects import (
    load_ability_flags_from_effects,
    normalized_payload,
)
from roco.generated import catalog_hot as hot


ROOT = Path(__file__).resolve().parents[1]
RULES_PATH = ROOT / "roco" / "compiler" / "rules" / "ability_flags_from_effects.jsonl"
PAK_DATA = ROOT / "pak-public-kit" / "output" / "data"


def _write(path: Path, rows: list[dict | str]) -> None:
    lines = []
    for row in rows:
        if isinstance(row, str):
            lines.append(row)
        else:
            lines.append(json.dumps(row, ensure_ascii=False))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _stub_effect_conf(effect_id: int, editor_name: str, effect_param) -> dict[int, dict]:
    """Build a stub EFFECT_CONF dict.

    ``effect_param`` is forwarded as-is so individual reject tests can
    push wrong-shape values (bare list, dict with extra keys, …) past
    the loader and verify the failure mode.  The "good" shape used in
    most tests is ``[{"params": [<buff_id>]}, {"params": [1]}]`` —
    matching the real pak slot wrapping.
    """
    return {effect_id: {"id": effect_id, "editor_name": editor_name, "type": 3, "effect_order": 76, "effect_param": effect_param}}


def _good_param(buff_id: int = 20070010) -> list[dict]:
    """Canonical pak shape used wherever a test wants the loader to accept."""
    return [{"params": [buff_id]}, {"params": [1]}]


# ── invariants ─────────────────────────────────────────────────────────────


def test_ability_flag_names_in_enum():
    """The heal-on-status names must exist on :class:`AbilityFlag`."""
    assert AbilityFlag.HEAL_ON_BURN_DAMAGE.value > 0
    assert AbilityFlag.HEAL_ON_POISON_DAMAGE.value > 0


def test_ability_flag_bits_are_power_of_two():
    """Defensive: any new ability flag bit must be a unique power of two."""
    seen: set[int] = set()
    for member in AbilityFlag:
        bit = int(member.value)
        if bit == 0:
            continue
        assert bit & (bit - 1) == 0, f"{member.name}={bit} is not a power of two"
        assert bit not in seen, f"duplicate bit for {member.name}: {bit}"
        seen.add(bit)


# ── loader: accept against real rules + pak ───────────────────────────────


def test_loader_accepts_real_rules():
    """Real ``ability_flags_from_effects.jsonl`` + real pak EFFECT_CONF must load."""
    table = load_ability_flags_from_effects()
    # 5C-iii ships exactly four rows.
    assert set(table.keys()) == {1076001, 1076002, 1076003, 1076004}
    assert table[1076004].flag_name == "HEAL_ON_BURN_DAMAGE"
    for eid in (1076001, 1076002, 1076003):
        assert table[eid].flag_name == "HEAL_ON_POISON_DAMAGE"


def test_normalized_payload_is_sorted_tuple():
    """``normalized_payload`` must be deterministic for SOURCE_HASH input."""
    table = load_ability_flags_from_effects()
    payload = normalized_payload(table)
    assert payload == tuple(sorted(payload, key=lambda pair: pair[0]))
    # And ``ability_flags_codegen`` re-exports the same thing.
    assert ability_flags_codegen.normalized_payload(table) == payload


# ── loader reject paths (tmp + stub) ──────────────────────────────────────


def test_loader_rejects_unknown_effect_id(tmp_path):
    fake = tmp_path / "rules.jsonl"
    _write(fake, [{
        "effect_id": 99999999,
        "pak_editor_name": "x",
        "flag": "HEAL_ON_BURN_DAMAGE",
        "evidence": "EFFECT_CONF.json[99999999].editor_name='x'",
    }])
    with pytest.raises(RuntimeError, match=r"line 1.*not in EFFECT_CONF"):
        load_ability_flags_from_effects(rules_path=fake, effect_conf={})


def test_loader_rejects_editor_name_drift(tmp_path):
    fake = tmp_path / "rules.jsonl"
    _write(fake, [{
        "effect_id": 12345,
        "pak_editor_name": "中毒变寄生",
        "flag": "HEAL_ON_POISON_DAMAGE",
        "evidence": "EFFECT_CONF.json[12345].editor_name='中毒变寄生'",
    }])
    conf = _stub_effect_conf(12345, "驱散蓄力", _good_param())
    with pytest.raises(RuntimeError, match=r"pak_editor_name.*does not match"):
        load_ability_flags_from_effects(rules_path=fake, effect_conf=conf)


def test_loader_rejects_unknown_flag_name(tmp_path):
    fake = tmp_path / "rules.jsonl"
    _write(fake, [{
        "effect_id": 12345,
        "pak_editor_name": "中毒变寄生",
        "flag": "MADE_UP_FLAG",
        "evidence": "EFFECT_CONF.json[12345].editor_name='中毒变寄生'",
    }])
    conf = _stub_effect_conf(12345, "中毒变寄生", _good_param())
    with pytest.raises(RuntimeError, match=r"flag 'MADE_UP_FLAG' is not an AbilityFlag member"):
        load_ability_flags_from_effects(rules_path=fake, effect_conf=conf)


def test_loader_rejects_evidence_prefix(tmp_path):
    fake = tmp_path / "rules.jsonl"
    _write(fake, [{
        "effect_id": 12345,
        "pak_editor_name": "中毒变寄生",
        "flag": "HEAL_ON_POISON_DAMAGE",
        "evidence": "see pak somewhere",
    }])
    conf = _stub_effect_conf(12345, "中毒变寄生", _good_param())
    with pytest.raises(RuntimeError, match=r"evidence must start with"):
        load_ability_flags_from_effects(rules_path=fake, effect_conf=conf)


def test_loader_rejects_duplicate_effect_id(tmp_path):
    fake = tmp_path / "rules.jsonl"
    row = {
        "effect_id": 12345,
        "pak_editor_name": "中毒变寄生",
        "flag": "HEAL_ON_POISON_DAMAGE",
        "evidence": "EFFECT_CONF.json[12345].editor_name='中毒变寄生'",
    }
    _write(fake, [row, row])
    conf = _stub_effect_conf(12345, "中毒变寄生", _good_param())
    with pytest.raises(RuntimeError, match=r"duplicate effect_id 12345"):
        load_ability_flags_from_effects(rules_path=fake, effect_conf=conf)


def test_loader_rejects_multiplier_not_one(tmp_path):
    """Boundary 2: ``effect_param[1] != [1]`` must fail loud — no defaulting."""
    fake = tmp_path / "rules.jsonl"
    _write(fake, [{
        "effect_id": 12345,
        "pak_editor_name": "中毒变寄生",
        "flag": "HEAL_ON_POISON_DAMAGE",
        "evidence": "EFFECT_CONF.json[12345].editor_name='中毒变寄生'",
    }])
    conf = _stub_effect_conf(12345, "中毒变寄生", [{"params": [20070010]}, {"params": [2]}])
    with pytest.raises(RuntimeError, match=r"effect_param\[1\]\.params expected exactly \[1\]"):
        load_ability_flags_from_effects(rules_path=fake, effect_conf=conf)


def test_loader_rejects_effect_param_wrong_length(tmp_path):
    fake = tmp_path / "rules.jsonl"
    _write(fake, [{
        "effect_id": 12345,
        "pak_editor_name": "中毒变寄生",
        "flag": "HEAL_ON_POISON_DAMAGE",
        "evidence": "EFFECT_CONF.json[12345].editor_name='中毒变寄生'",
    }])
    conf = _stub_effect_conf(12345, "中毒变寄生", [{"params": [20070010]}])  # length 1
    with pytest.raises(RuntimeError, match=r"effect_param expected length 2"):
        load_ability_flags_from_effects(rules_path=fake, effect_conf=conf)


def test_loader_rejects_empty_slot0(tmp_path):
    fake = tmp_path / "rules.jsonl"
    _write(fake, [{
        "effect_id": 12345,
        "pak_editor_name": "中毒变寄生",
        "flag": "HEAL_ON_POISON_DAMAGE",
        "evidence": "EFFECT_CONF.json[12345].editor_name='中毒变寄生'",
    }])
    conf = _stub_effect_conf(12345, "中毒变寄生", [{"params": []}, {"params": [1]}])
    with pytest.raises(RuntimeError, match=r"effect_param\[0\]\.params expected a non-empty"):
        load_ability_flags_from_effects(rules_path=fake, effect_conf=conf)


def test_loader_rejects_bare_list_slot(tmp_path):
    """Bare-list slot (without ``{'params': ...}``) must be rejected — not silently accepted."""
    fake = tmp_path / "rules.jsonl"
    _write(fake, [{
        "effect_id": 12345,
        "pak_editor_name": "中毒变寄生",
        "flag": "HEAL_ON_POISON_DAMAGE",
        "evidence": "EFFECT_CONF.json[12345].editor_name='中毒变寄生'",
    }])
    conf = _stub_effect_conf(12345, "中毒变寄生", [[20070010], [1]])
    with pytest.raises(RuntimeError, match=r"effect_param\[0\] expected \{'params': \[\.\.\.\]\} shape"):
        load_ability_flags_from_effects(rules_path=fake, effect_conf=conf)


def test_loader_skips_comments_and_blank_lines(tmp_path):
    """``#`` comments + blank lines must be skipped (consistent with other loaders)."""
    fake = tmp_path / "rules.jsonl"
    fake.write_text(
        "# header comment\n"
        "\n"
        "# Another comment line\n"
        + json.dumps({
            "effect_id": 12345,
            "pak_editor_name": "中毒变寄生",
            "flag": "HEAL_ON_POISON_DAMAGE",
            "evidence": "EFFECT_CONF.json[12345].editor_name='中毒变寄生'",
        }, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    conf = _stub_effect_conf(12345, "中毒变寄生", _good_param())
    table = load_ability_flags_from_effects(rules_path=fake, effect_conf=conf)
    assert set(table.keys()) == {12345}
    assert table[12345].flag_name == "HEAL_ON_POISON_DAMAGE"


# ── ability-only gate (boundary 1) ────────────────────────────────────────


def test_generate_effect_rows_skill_path_rejects_ability_flag_outcome():
    """Boundary 1: a skill that references an ability-flag effect_id must
    not be silently absorbed.

    Construct a skill_result entry referencing effect_id ``1076001`` (a
    real ability-flag rule) and call ``generate_effect_rows`` with the
    default ``allow_ability_flags=False`` (skill-builder semantics).
    The function must raise — the alternative (silent skip / covered /
    ignored) would let a future pak change wire passive heal-on-damage
    semantics into a per-cast skill row, which the runtime would not
    interpret correctly.
    """
    pak = PakTables(PAK_DATA)
    skill_row = {
        "skill_result": [{
            "effect_id": 1076001,
            "result_target_type": 1,
            "cast_moment": 11,
            "success_rate": 10000,
        }],
    }
    with pytest.raises(RuntimeError, match=r"AbilityFlagOutcome leaked into a non-ability"):
        generate_effect_rows(skill_row, pak)


def test_generate_effect_rows_ability_path_accepts_ability_flag_outcome():
    """Symmetric positive: ability builder accepts the outcome and drops it
    from rows / ignored / gaps.  ABILITY_FLAGS is then populated later by
    ``ability_flags_codegen.populate`` — verified by other tests.
    """
    pak = PakTables(PAK_DATA)
    skill_row = {
        "skill_result": [{
            "effect_id": 1076001,
            "result_target_type": 1,
            "cast_moment": 11,
            "success_rate": 10000,
        }],
    }
    rows, ignored, gaps = generate_effect_rows(skill_row, pak, allow_ability_flags=True)
    assert rows == []
    assert ignored == []
    assert gaps == []


# ── codegen join correctness (boundary 3) ─────────────────────────────────


def _make_db_with_ability_effect_ids(tmp_path: Path, mapping: list[tuple[int, int, int]]) -> sqlite3.Connection:
    """Build an in-memory-style temp DB containing the minimal schema for
    ``ability_flags_codegen.populate`` to join.

    ``mapping`` is a list of ``(ability_id, effect_id, sort_order)`` tuples.
    """
    db = tmp_path / "test.db"
    conn = sqlite3.connect(str(db))
    conn.execute(
        "CREATE TABLE ability_effect_ids ("
        " ability_id INTEGER NOT NULL,"
        " source_ability_id INTEGER NOT NULL,"
        " effect_id INTEGER NOT NULL,"
        " timing_code INTEGER NOT NULL,"
        " target_type INTEGER NOT NULL,"
        " success_rate INTEGER NOT NULL,"
        " sort_order INTEGER NOT NULL,"
        " PRIMARY KEY (ability_id, sort_order))"
    )
    for ability_id, effect_id, sort_order in mapping:
        conn.execute(
            "INSERT INTO ability_effect_ids "
            "(ability_id, source_ability_id, effect_id, timing_code, target_type, success_rate, sort_order) "
            "VALUES (?, ?, ?, 11, 1, 10000, ?)",
            (ability_id, ability_id * 1000, effect_id, sort_order),
        )
    return conn


def test_populate_ors_bits_via_join(tmp_path):
    """Boundary 3: ABILITY_FLAGS comes from ``ability_effect_ids`` ⨝ rules.

    Mock a tiny DB with ability 7 referencing both 1076001 (POISON heal) and
    1076004 (BURN heal); ability 9 referencing only 1076004.  After
    ``populate`` the ability_flags array must reflect the OR of all matched
    rules and nothing else.
    """
    conn = _make_db_with_ability_effect_ids(tmp_path, [
        (7, 1076001, 0),
        (7, 1076004, 1),
        (9, 1076004, 0),
    ])
    table = load_ability_flags_from_effects()
    ability_flags = [0] * 16
    matched = ability_flags_codegen.populate(conn, effect_to_flag=table, ability_flags=ability_flags)
    assert matched == 3  # three (ability_id, effect_id) pairs joined
    expected_seven = int(AbilityFlag.HEAL_ON_POISON_DAMAGE) | int(AbilityFlag.HEAL_ON_BURN_DAMAGE)
    assert ability_flags[7] == expected_seven
    assert ability_flags[9] == int(AbilityFlag.HEAL_ON_BURN_DAMAGE)
    # All other slots remain zero — populate must not touch them.
    for idx, value in enumerate(ability_flags):
        if idx in {7, 9}:
            continue
        assert value == 0, f"unexpected non-zero bit at ability_id={idx}: {value}"


def test_populate_raises_on_out_of_range_ability_id(tmp_path):
    """A row whose ability_id exceeds the compiled range should fail loud."""
    conn = _make_db_with_ability_effect_ids(tmp_path, [(50, 1076001, 0)])
    table = load_ability_flags_from_effects()
    ability_flags = [0] * 4  # capacity smaller than the row's ability_id
    with pytest.raises(RuntimeError, match=r"outside of compiled range"):
        ability_flags_codegen.populate(conn, effect_to_flag=table, ability_flags=ability_flags)


# ── live catalog drift check ──────────────────────────────────────────────


def test_catalog_abilityflag_slots_match_expected_pak_consumers():
    """The live ``hot.ABILITY_FLAGS`` table must show 仁心 / 耐活王 with
    the bits driven by the rules JSONL.

    Ids 200152 (仁心) and 200240 (耐活王) are pak feature ids ≠ DB
    normalized ids.  Resolve the normalized id via the live SQLite store
    so the assertion runs end-to-end against the build that just produced
    the catalog.

    A failure here means one of: (a) the rules file no longer covers
    those effect_ids, (b) parse_pak / build_db lost ability_effect_ids
    provenance, or (c) the codegen join did not run.
    """
    db_path = ROOT / "_db" / "data.db"
    if not db_path.exists():
        pytest.skip("_db/data.db missing; run `uv run python -m roco.data.build_db` first")
    conn = sqlite3.connect(str(db_path))
    try:
        for ability_name, expected_flag in (("仁心", AbilityFlag.HEAL_ON_BURN_DAMAGE),
                                            ("耐活王", AbilityFlag.HEAL_ON_POISON_DAMAGE)):
            row = conn.execute(
                "SELECT id FROM abilities WHERE name = ?", (ability_name,)
            ).fetchone()
            assert row, f"ability {ability_name!r} missing from abilities table"
            normalized_id = int(row[0])
            actual = hot.ABILITY_FLAGS[normalized_id]
            assert actual & int(expected_flag), (
                f"ability {ability_name!r} (normalized={normalized_id}): "
                f"expected bit {expected_flag.name} set, got 0x{actual:x}"
            )
    finally:
        conn.close()
