"""Self-check tests for the pak effect family catalog."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import pytest

from roco.compiler import build_effect_families as bef


ROOT = Path(__file__).resolve().parents[1]
CATALOG_JSONL = ROOT / "roco" / "compiler" / "rules" / "effect_families.jsonl"
PAK_DATA = ROOT / "pak-public-kit" / "output" / "data"

REQUIRED_FIELDS = (
    "family_key",
    "source_table",
    "pak_type",
    "pak_effect_order",
    "buff_prefix",
    "count",
    "example_source_ids",
    "editor_names",
    "param_shape",
    "cross_refs",
    "sample_skill_consumers",
    "sample_ability_consumers",
    "used_consumer_count",
    "desc_note_refs",
    "coverage_status",
    "coverage_breakdown",
    "pak_evidence",
    "ignored_candidate",
    "ignored_candidate_reason",
    "ignored_candidate_source_ids",
)

SPECULATIVE_WORDS = ("likely", "would", "probably", "possibly")

BLOCKER_FAMILY_KEYS = (
    "effect_conf:t3:o19",
    "effect_conf:t3:o34",
    "effect_conf:t1:o5",
    "effect_conf:t3:o22",
    "effect_conf:t1:o35",
    "buff_conf_direct:prefix_2040",
    "buff_conf_direct:prefix_2003",
)
BLOCKER_ALLOWED_STATUSES = {"gap", "exact_jsonl_partial", "mixed"}


@pytest.fixture(scope="module")
def catalog() -> list[dict]:
    """Read the on-disk catalog into a list of dicts."""
    assert CATALOG_JSONL.exists(), (
        "effect_families.jsonl missing — run "
        "`uv run python -m roco.compiler.build_effect_families`"
    )
    with CATALOG_JSONL.open("r", encoding="utf-8") as fp:
        return [json.loads(line) for line in fp if line.strip()]


@pytest.fixture(scope="module")
def by_key(catalog: list[dict]) -> dict[str, dict]:
    return {f["family_key"]: f for f in catalog}


@pytest.fixture(scope="module")
def pak_tables():
    from roco.compiler.effect_codegen.pak import PakTables
    return PakTables(PAK_DATA)


# ── well-formedness ───────────────────────────────────────────────────────


def test_effect_families_jsonl_well_formed(catalog, pak_tables):
    """Every row has required fields, valid coverage_status, valid source_table.

    ``example_source_ids`` route by ``source_table``: EFFECT_CONF entries must
    have ids in EFFECT_CONF.json; BUFF_CONF_DIRECT entries must have ids in
    BUFF_CONF.json.  Catches schema drift / wrong-table pollution.
    """
    assert catalog, "catalog is empty"
    effect_conf = pak_tables.effect_conf
    buff_conf = pak_tables.buff_conf
    for family in catalog:
        for field in REQUIRED_FIELDS:
            assert field in family, (
                f"family {family.get('family_key')!r} missing field {field!r}"
            )
        assert family["coverage_status"] in bef.COVERAGE_STATUSES, (
            f"{family['family_key']}: unknown coverage_status "
            f"{family['coverage_status']!r}"
        )
        assert family["source_table"] in {"EFFECT_CONF", "BUFF_CONF_DIRECT"}
        target_table = effect_conf if family["source_table"] == "EFFECT_CONF" else buff_conf
        for sid in family["example_source_ids"]:
            assert sid in target_table, (
                f"{family['family_key']}: example_source_id {sid} not in "
                f"{family['source_table']}"
            )


def test_effect_families_pak_evidence_nonempty(catalog):
    """Every family must cite at least one pak/Lua/JSONL source string."""
    for family in catalog:
        assert family["pak_evidence"], (
            f"{family['family_key']}: pak_evidence is empty"
        )


def test_effect_families_no_speculative_language(catalog):
    """No 'likely / would / probably / possibly' in any catalog string field.

    Catalog records pak facts, not guesses.  This guard fires if anyone
    backslides on the rule.
    """
    def _walk(value, path: str):
        if isinstance(value, str):
            lower = value.lower()
            for bad in SPECULATIVE_WORDS:
                # Match as whole word to avoid false positives in URLs / ids.
                idx = 0
                while True:
                    idx = lower.find(bad, idx)
                    if idx < 0:
                        break
                    before = lower[idx - 1] if idx > 0 else ""
                    after = lower[idx + len(bad)] if idx + len(bad) < len(lower) else ""
                    if not before.isalnum() and not after.isalnum():
                        raise AssertionError(
                            f"speculative word {bad!r} found at {path}: {value!r}"
                        )
                    idx += len(bad)
        elif isinstance(value, dict):
            for k, v in value.items():
                _walk(v, f"{path}.{k}")
        elif isinstance(value, list):
            for i, v in enumerate(value):
                _walk(v, f"{path}[{i}]")

    for family in catalog:
        _walk(family, family["family_key"])


# ── completeness ─────────────────────────────────────────────────────────


def test_effect_families_effect_conf_completeness(catalog, pak_tables):
    """Every actual (type, effect_order) combo in EFFECT_CONF is in the catalog."""
    expected: set[str] = set()
    for rec in pak_tables.effect_conf.values():
        t = int(rec.get("type", 0))
        o = int(rec.get("effect_order", 0))
        expected.add(f"effect_conf:t{t}:o{o}")
    actual = {f["family_key"] for f in catalog if f["source_table"] == "EFFECT_CONF"}
    missing = expected - actual
    extra = actual - expected
    assert not missing, f"catalog missing EFFECT_CONF families: {sorted(missing)}"
    assert not extra, f"catalog has EFFECT_CONF families not in pak: {sorted(extra)}"


def test_effect_families_buff_conf_direct_completeness(catalog, pak_tables):
    """Every direct BUFF_CONF id referenced by canonical skills/abilities
    has an entry in the catalog under its expected family_key.

    "Direct" = ``skill_result.effect_id`` / ``effect_list.effect_id`` that
    exists in BUFF_CONF but NOT in EFFECT_CONF (e.g. 20400420 天光).
    """
    canonical_dir = ROOT / "_data" / "canonical"
    consumer_ids: set[int] = set()
    for filename in ("skills.jsonl", "abilities.jsonl"):
        path = canonical_dir / filename
        if not path.exists():
            continue
        with path.open("r", encoding="utf-8") as fp:
            for raw in fp:
                if not raw.strip():
                    continue
                rec = json.loads(raw)
                source_fields = rec.get("source_fields") or {}
                rows = source_fields.get("skill_result") or source_fields.get("effect_list") or []
                for entry in rows:
                    if isinstance(entry, dict) and entry.get("effect_id"):
                        consumer_ids.add(int(entry["effect_id"]))

    direct_buff_ids = {
        eid for eid in consumer_ids
        if eid in pak_tables.buff_conf and eid not in pak_tables.effect_conf
    }
    expected_keys: set[str] = set()
    for bid in direct_buff_ids:
        key, _ = bef._buff_family_key(bid, pak_tables.buff_conf)
        expected_keys.add(key)
    actual = {f["family_key"] for f in catalog if f["source_table"] == "BUFF_CONF_DIRECT"}
    missing = expected_keys - actual
    extra = actual - expected_keys
    assert not missing, f"catalog missing BUFF_CONF_DIRECT families: {sorted(missing)}"
    assert not extra, f"catalog has BUFF_CONF_DIRECT families not used by canonical: {sorted(extra)}"


def test_ignored_candidate_only_when_all_sources_visual(catalog):
    """``ignored_candidate=true`` must require **every** source_id to hit a
    visual-only keyword.  Single-keyword hits inside a mixed family land
    in ``ignored_candidate_source_ids`` instead.

    Locks in the fix for the regression where a single ``月牙雪熊飘字用``
    row marked the whole ``buff_conf_direct:prefix_2040`` family as
    ignored despite hosting real blockers (天光 / 月光合奏 / 击鼓传花).
    """
    visual_keywords = ("动效", "飘字", "动画", "特效")
    for f in catalog:
        per_id_hits = f.get("ignored_candidate_source_ids") or []
        if f["ignored_candidate"]:
            assert per_id_hits, (
                f"{f['family_key']}: ignored_candidate=true but no per-id hits"
            )
            assert len(per_id_hits) == f["count"], (
                f"{f['family_key']}: ignored_candidate=true but only "
                f"{len(per_id_hits)}/{f['count']} source ids carry visual "
                f"keywords"
            )
        # Conversely, per-id hits without family flag means there are real
        # non-visual source ids in the family — sanity check none of the
        # editor_names from per-id hits leak into the family-level flag.
        for hit in per_id_hits:
            assert any(kw in hit["editor_name"] for kw in visual_keywords), (
                f"{f['family_key']}: per-id hit {hit} editor_name lacks "
                "visual keyword"
            )


def test_effect_families_covers_blocker_gaps(by_key):
    """Known blockers must appear in catalog with a gap-style coverage_status.

    Extra layer on top of completeness — if any of these blockers flip to
    ``auto_structural``/``exact_jsonl``/``ignored`` that means kernel
    actually implemented the family; update this list with intent rather
    than letting the change pass silently.
    """
    for key in BLOCKER_FAMILY_KEYS:
        assert key in by_key, f"blocker family {key!r} missing from catalog"
        status = by_key[key]["coverage_status"]
        assert status in BLOCKER_ALLOWED_STATUSES, (
            f"blocker {key!r} now reports coverage_status={status!r}; "
            "if kernel implemented this family, update BLOCKER_ALLOWED_STATUSES "
            "with intent."
        )


# ── check mode ───────────────────────────────────────────────────────────


def test_effect_families_check_mode_clean():
    """``--check`` exit 0 when on-disk catalog matches a fresh build.

    Equivalent to a PR-time gate: contributors must regenerate the catalog
    after touching anything that changes the build output.
    """
    assert bef.main(["--check"]) == 0
