"""Phase 5C-iii: ABILITY_FLAGS codegen / loader / classifier tests.

Covers the four hard boundaries:

1. **ability-only gate** — :func:`generate_effect_rows` with
   ``allow_ability_flags=False`` rejects an :class:`AbilityFlagOutcome`
   (skill path must not silently swallow ability-passive effect_ids).
2. **multiplier reject** — loader rejects ``effect_param[1] != [1]``
   (and the shape variants around it).  No defaulting / truncation.
3. **ABILITY_FLAGS = ability_effect_ids ⨝ pak-derived semantics** — codegen
   populates the per-ability mask from generated in-memory provenance rows
   joined with the derived semantic table.

(End-to-end residual heal — boundary 4 — lives in
``tests/test_status_damage_heal.py``.)
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from roco.common.enums import AbilityFlag
from roco.compiler_v2 import ability_flags as ability_flag_artifact
from roco.compiler_v2.effect_codegen import (
    AbilityFlagOutcome,
    EmitOutcome,
    GapOutcome,
    PakTables,
    generate_effect_rows,
)
from roco.compiler_v2.effect_codegen.ability_flags_from_effects import (
    load_ability_flags_from_effects,
    normalized_payload,
)
from roco.generated import catalog_debug as debug
from roco.generated import catalog_hot as hot


ROOT = Path(__file__).resolve().parents[1]
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
    assert AbilityFlag.FREEZE_COUNTS_AS_METEOR.value > 0


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


def test_loader_accepts_real_pak_derivation():
    """Real pak derives the current ability flag skill_result ids."""
    table = load_ability_flags_from_effects()
    assert set(table.keys()) == {1066001, 20400410, 21430010, 21540010, 21540040}
    assert table[1066001].flag_name == "SHUFFLE_SKILLS_REDUCE_LAST"
    assert table[20400410].flag_name == "FREEZE_COUNTS_AS_METEOR"
    assert table[21540010].flag_name == "HEAL_ON_POISON_DAMAGE"
    assert table[21540040].flag_name == "HEAL_ON_BURN_DAMAGE"
    assert table[21430010].flag_name == "MARK_STACK_NO_REPLACE"


def test_loader_routes_only_structural_freeze_meteor_order40_buff():
    """月牙雪糕's order-40 virtual-layer chain is an ability flag; 嫉妒 is not."""
    table = load_ability_flags_from_effects()
    assert table[20400410].flag_name == "FREEZE_COUNTS_AS_METEOR"
    assert 20400210 not in table


def test_normalized_payload_is_sorted_tuple():
    """``normalized_payload`` must be deterministic for SOURCE_HASH input."""
    table = load_ability_flags_from_effects()
    payload = normalized_payload(table)
    assert payload == tuple(sorted(payload, key=lambda pair: pair[0]))
    # And the catalog artifact helper re-exports the same thing.
    assert ability_flag_artifact.normalized_payload(table) == payload


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

    Construct a skill_result entry referencing effect_id ``21540010`` (a
    real direct ``BUFF_CONF`` ability-flag rule) and call ``generate_effect_rows`` with the
    default ``allow_ability_flags=False`` (skill-builder semantics).
    The function must raise — the alternative (silent skip / covered /
    skipped) would let a future pak change wire passive heal-on-damage
    semantics into a per-cast skill row, which the runtime would not
    interpret correctly.
    """
    pak = PakTables(PAK_DATA)
    skill_row = {
        "skill_result": [{
            "effect_id": 21540010,
            "result_target_type": 1,
            "cast_moment": 11,
            "success_rate": 10000,
        }],
    }
    with pytest.raises(RuntimeError, match=r"AbilityFlagOutcome leaked into a non-ability"):
        generate_effect_rows(skill_row, pak)


def test_generate_effect_rows_ability_path_accepts_ability_flag_outcome():
    """Symmetric positive: ability builder accepts the outcome and drops it
    from rows / gaps.  ABILITY_FLAGS is then populated later by
    ``ability_flags.populate`` — verified by other tests.
    """
    pak = PakTables(PAK_DATA)
    skill_row = {
        "skill_result": [{
            "effect_id": 21540010,
            "result_target_type": 1,
            "cast_moment": 11,
            "success_rate": 10000,
        }],
    }
    rows, gaps = generate_effect_rows(skill_row, pak, allow_ability_flags=True)
    assert rows == []
    assert gaps == []


def test_generate_effect_rows_ability_path_accepts_direct_buff_flag_outcome():
    """Direct BUFF_CONF passive rows can compile to ABILITY_FLAGS too."""
    pak = PakTables(PAK_DATA)
    skill_row = {
        "skill_result": [{
            "effect_id": 21430010,
            "result_target_type": 1,
            "cast_moment": 11,
            "success_rate": 10000,
        }],
    }
    rows, gaps = generate_effect_rows(skill_row, pak, allow_ability_flags=True)
    assert rows == []
    assert gaps == []


def test_generate_effect_rows_ability_path_accepts_freeze_meteor_flag_outcome():
    """The 月牙雪糕 direct BUFF_CONF row compiles into ABILITY_FLAGS."""
    pak = PakTables(PAK_DATA)
    skill_row = {
        "skill_result": [{
            "effect_id": 20400410,
            "result_target_type": 1,
            "cast_moment": 11,
            "success_rate": 10000,
        }],
    }
    rows, gaps = generate_effect_rows(skill_row, pak, allow_ability_flags=True)
    assert rows == []
    assert gaps == []


# ── codegen join correctness (boundary 3) ─────────────────────────────────


def _ability_effect_id_rows(mapping: list[tuple[int, int, int]]) -> list[tuple[int, int, int, int, int, int, int]]:
    """Return ``(ability_id, source_ability_id, effect_id, timing, target, rate, sort_order)`` rows."""

    return [
        (ability_id, ability_id * 1000, effect_id, 11, 1, 10000, sort_order)
        for ability_id, effect_id, sort_order in mapping
    ]


def test_populate_ors_bits_via_join():
    """Boundary 3: ABILITY_FLAGS comes from ``ability_effect_ids`` ⨝ rules.

    Mock tiny provenance rows with ability 7 referencing 21540010 (POISON heal),
    21540040 (BURN heal), and 21430010 (mark stacking); ability 9
    referencing only 21540040.  After ``populate`` the ability_flags array
    must reflect the OR of all matched rules and nothing else.
    """
    rows = _ability_effect_id_rows([
        (7, 21540010, 0),
        (7, 21540040, 1),
        (7, 21430010, 2),
        (9, 21540040, 0),
    ])
    table = load_ability_flags_from_effects()
    ability_flags = [0] * 16
    matched = ability_flag_artifact.populate(rows, effect_to_flag=table, ability_flags=ability_flags)
    assert matched == 4  # four (ability_id, effect_id) pairs joined
    expected_seven = (
        int(AbilityFlag.HEAL_ON_POISON_DAMAGE)
        | int(AbilityFlag.HEAL_ON_BURN_DAMAGE)
        | int(AbilityFlag.MARK_STACK_NO_REPLACE)
    )
    assert ability_flags[7] == expected_seven
    assert ability_flags[9] == int(AbilityFlag.HEAL_ON_BURN_DAMAGE)
    # All other slots remain zero — populate must not touch them.
    for idx, value in enumerate(ability_flags):
        if idx in {7, 9}:
            continue
        assert value == 0, f"unexpected non-zero bit at ability_id={idx}: {value}"


def test_populate_raises_on_out_of_range_ability_id():
    """A row whose ability_id exceeds the compiled range should fail loud."""
    rows = _ability_effect_id_rows([(50, 21540010, 0)])
    table = load_ability_flags_from_effects()
    ability_flags = [0] * 4  # capacity smaller than the row's ability_id
    with pytest.raises(RuntimeError, match=r"outside of compiled range"):
        ability_flag_artifact.populate(rows, effect_to_flag=table, ability_flags=ability_flags)


# ── live catalog drift check ──────────────────────────────────────────────


def test_catalog_abilityflag_slots_match_expected_pak_consumers():
    """The live ``hot.ABILITY_FLAGS`` table must show 仁心 / 耐活王 with
    the bits driven by Python semantic bindings.

    Ids 200152 (仁心) and 200240 (耐活王) are pak feature ids, while
    ``hot.ABILITY_FLAGS`` is indexed by the generated catalog id.  Resolve
    the catalog id through ``catalog_debug.ABILITY_NAMES``.

    A failure here means one of: (a) the rules file no longer covers
    those effect_ids, (b) parse_pak/catalog_compiler lost ability_effect_ids
    provenance, or (c) the codegen join did not run.
    """
    for ability_name, expected_flag in (("仁心", AbilityFlag.HEAL_ON_BURN_DAMAGE),
                                        ("耐活王", AbilityFlag.HEAL_ON_POISON_DAMAGE),
                                        ("吟游之弦", AbilityFlag.MARK_STACK_NO_REPLACE)):
        assert ability_name in debug.ABILITY_NAMES
        normalized_id = debug.ABILITY_NAMES.index(ability_name)
        actual = hot.ABILITY_FLAGS[normalized_id]
        assert actual & int(expected_flag), (
            f"ability {ability_name!r} (normalized={normalized_id}): "
            f"expected bit {expected_flag.name} set, got 0x{actual:x}"
        )
