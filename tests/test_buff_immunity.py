"""Validation + drift tests for the Phase 2A immunity framework spike.

All reject tests use ``tmp_path`` + stub buff_conf so the real
``rules/buff_immunity.jsonl`` is never modified.  The accept + drift
tests read the real artifacts to catch real-world regressions.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from roco.compiler.codegen import buff_immunity_codegen as bic
from roco.compiler.effect_codegen import buff_immunity_decoders as bid
from roco.generated import buff_immunity_table as generated


ROOT = Path(__file__).resolve().parents[1]


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n",
        encoding="utf-8",
    )


def _stub_conf(buff_id: int, desc: str) -> dict[int, dict]:
    return {buff_id: {"id": buff_id, "desc": desc}}


# ── invariants ─────────────────────────────────────────────────────────────


def test_immunity_specs_consistent():
    """IMMUNITY_SPECS must have no duplicate tag/const_name/bit and bits are 2^n."""
    tags = [s.tag for s in bid.IMMUNITY_SPECS]
    consts = [s.const_name for s in bid.IMMUNITY_SPECS]
    bits = [s.bit for s in bid.IMMUNITY_SPECS]
    assert len(set(tags)) == len(tags), f"duplicate tag in IMMUNITY_SPECS: {tags}"
    assert len(set(consts)) == len(consts), f"duplicate const_name: {consts}"
    assert len(set(bits)) == len(bits), f"duplicate bit: {bits}"
    for spec in bid.IMMUNITY_SPECS:
        assert spec.bit > 0 and (spec.bit & (spec.bit - 1)) == 0, (
            f"bit not a power of two: {spec}"
        )
        assert spec.keyword, f"empty keyword for {spec.tag}"


# ── accept (real rules + real pak) ─────────────────────────────────────────


def test_loader_accepts_valid_rules():
    """Real ``rules/buff_immunity.jsonl`` loads and matches the generated table.

    This is the live happy path: rules + pak + generated stay in sync.
    """
    loaded = bid.load_buff_immunity_table()
    assert loaded == generated.BUFF_IMMUNITY_TABLE


# ── reject paths (tmp jsonl, stub buff_conf) ───────────────────────────────


def test_loader_rejects_unknown_buff_id(tmp_path):
    fake = tmp_path / "fake.jsonl"
    _write_jsonl(fake, [{
        "buff_id": 99999999,
        "pak_editor_name": "x",
        "pak_desc": "y",
        "immunities": ["force_switch"],
        "evidence": "BUFF_CONF.json[99999999].desc='y'",
    }])
    with pytest.raises(RuntimeError, match=r"line 1.*not in BUFF_CONF"):
        bid.load_buff_immunity_table(rules_path=fake, buff_conf={})


def test_loader_rejects_desc_mismatch(tmp_path):
    fake = tmp_path / "fake.jsonl"
    _write_jsonl(fake, [{
        "buff_id": 12345,
        "pak_editor_name": "x",
        "pak_desc": "免疫吹飞XXX",  # diverges from stub
        "immunities": ["force_switch"],
        "evidence": "BUFF_CONF.json[12345].desc='免疫吹飞XXX'",
    }])
    conf = _stub_conf(12345, "免疫吹飞")
    with pytest.raises(RuntimeError, match=r"pak_desc.*does not match"):
        bid.load_buff_immunity_table(rules_path=fake, buff_conf=conf)


def test_loader_rejects_flag_not_in_desc(tmp_path):
    """immunities=['energy_drain'] requires keyword 倾泻 in pak_desc."""
    fake = tmp_path / "fake.jsonl"
    _write_jsonl(fake, [{
        "buff_id": 12345,
        "pak_editor_name": "x",
        "pak_desc": "免疫吹飞",  # no 倾泻
        "immunities": ["energy_drain"],
        "evidence": "BUFF_CONF.json[12345].desc='免疫吹飞'",
    }])
    conf = _stub_conf(12345, "免疫吹飞")
    with pytest.raises(RuntimeError, match=r"requires keyword '倾泻'"):
        bid.load_buff_immunity_table(rules_path=fake, buff_conf=conf)


def test_loader_rejects_evidence_format(tmp_path):
    fake = tmp_path / "fake.jsonl"
    _write_jsonl(fake, [{
        "buff_id": 12345,
        "pak_editor_name": "x",
        "pak_desc": "免疫吹飞",
        "immunities": ["force_switch"],
        "evidence": "see pak somewhere",  # malformed
    }])
    conf = _stub_conf(12345, "免疫吹飞")
    with pytest.raises(RuntimeError, match=r"evidence must start with"):
        bid.load_buff_immunity_table(rules_path=fake, buff_conf=conf)


def test_loader_rejects_unknown_immunity_tag(tmp_path):
    fake = tmp_path / "fake.jsonl"
    _write_jsonl(fake, [{
        "buff_id": 12345,
        "pak_editor_name": "x",
        "pak_desc": "免疫吹飞",
        "immunities": ["made_up_tag"],
        "evidence": "BUFF_CONF.json[12345].desc='免疫吹飞'",
    }])
    conf = _stub_conf(12345, "免疫吹飞")
    with pytest.raises(RuntimeError, match=r"unknown immunity tag 'made_up_tag'"):
        bid.load_buff_immunity_table(rules_path=fake, buff_conf=conf)


def test_loader_rejects_duplicate_buff_id(tmp_path):
    """Two rows for the same buff_id must fail loudly.

    Without this guard the second row silently overwrites the first —
    catastrophic for any future merge conflict that resolves wrong, and
    contradicts the "strict validation" goal of the spike.
    """
    fake = tmp_path / "fake.jsonl"
    _write_jsonl(fake, [
        {
            "buff_id": 12345,
            "pak_editor_name": "x",
            "pak_desc": "免疫吹飞",
            "immunities": ["force_switch"],
            "evidence": "BUFF_CONF.json[12345].desc='免疫吹飞'",
        },
        {
            "buff_id": 12345,
            "pak_editor_name": "x2",
            "pak_desc": "免疫吹飞",
            "immunities": ["force_switch"],
            "evidence": "BUFF_CONF.json[12345].desc='免疫吹飞'",
        },
    ])
    conf = _stub_conf(12345, "免疫吹飞")
    with pytest.raises(RuntimeError, match=r"duplicate buff_id 12345.*line 1"):
        bid.load_buff_immunity_table(rules_path=fake, buff_conf=conf)


def test_loader_rejects_empty_immunities_list(tmp_path):
    fake = tmp_path / "fake.jsonl"
    _write_jsonl(fake, [{
        "buff_id": 12345,
        "pak_editor_name": "x",
        "pak_desc": "免疫吹飞",
        "immunities": [],
        "evidence": "BUFF_CONF.json[12345].desc='免疫吹飞'",
    }])
    conf = _stub_conf(12345, "免疫吹飞")
    with pytest.raises(RuntimeError, match=r"non-empty list"):
        bid.load_buff_immunity_table(rules_path=fake, buff_conf=conf)


# ── drift ──────────────────────────────────────────────────────────────────


def test_generated_table_matches_loader(tmp_path):
    """Re-render the generated module in memory and compare byte-for-byte.

    If this fails, ``uv run python -m roco.compiler.gen_prefix_map`` was
    not re-run after editing ``rules/buff_immunity.jsonl`` or
    ``IMMUNITY_SPECS``.
    """
    fresh_table = bid.load_buff_immunity_table()
    fresh_text = bic.render(fresh_table)
    on_disk = bic.DEFAULT_OUTPUT_PATH.read_text(encoding="utf-8")
    assert on_disk == fresh_text, (
        "roco/generated/buff_immunity_table.py is out of date; "
        "re-run `uv run python -m roco.compiler.gen_prefix_map`"
    )


def test_generated_status_immunity_map_exact_content():
    """Generated ``STATUS_IMMUNITY_FLAGS_BY_STATUS_TYPE`` must be the
    name-match join of ``IMMUNITY_SPECS`` × :class:`StatusType`, keyed by
    ``int(StatusType.X)``.  ``force_switch`` / ``energy_drain`` must not
    leak into this map — they are not StatusType members.
    """
    from roco.common.enums import StatusType
    from roco.generated.buff_immunity_table import (
        IMMUNITY_BURN,
        IMMUNITY_FREEZE,
        IMMUNITY_LEECH,
        IMMUNITY_POISON,
        STATUS_IMMUNITY_FLAGS_BY_STATUS_TYPE,
    )

    assert STATUS_IMMUNITY_FLAGS_BY_STATUS_TYPE == {
        int(StatusType.BURN):   IMMUNITY_BURN,
        int(StatusType.POISON): IMMUNITY_POISON,
        int(StatusType.FREEZE): IMMUNITY_FREEZE,
        int(StatusType.LEECH):  IMMUNITY_LEECH,
    }
    # Defensive: no StatusType value should map to force_switch /
    # energy_drain IMMUNITY_* bits, since those aren't status conditions.
    from roco.generated.buff_immunity_table import (
        IMMUNITY_ENERGY_DRAIN,
        IMMUNITY_FORCE_SWITCH,
    )
    for flag in STATUS_IMMUNITY_FLAGS_BY_STATUS_TYPE.values():
        assert not (flag & IMMUNITY_FORCE_SWITCH)
        assert not (flag & IMMUNITY_ENERGY_DRAIN)
