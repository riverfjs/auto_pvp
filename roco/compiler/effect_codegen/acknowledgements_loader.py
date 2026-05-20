"""Strict loader for ``rules/effect_gap_acknowledgements.jsonl``.

Phase 3 introduces acknowledgements as a parallel audit axis to the
existing emit / ignored / gap three-state contract.  An acknowledgement
is **not** a runtime decoder rule — it does not emit kernel ops.  It is
a compile-time declaration that a *used* :class:`effect_gaps` row has
been audited and assigned to one of:

* ``evidence_available_deferred`` — strong pak evidence (anchor keywords
  in consumer ``SKILL_CONF.desc``); kernel hook deferred to a later
  phase.
* ``evidence_available_weak`` — consumer desc visible but no anchor
  keyword; needs human review.
* ``evidence_missing`` — no consumer desc evidence available.
* ``confirmed_ignored`` — confirmed to have no battle-relevant
  semantics; safe to drop.

The validator implementation here mirrors the failure conditions listed
in the Phase 3 plan.  Tests in ``tests/test_effect_gap_acknowledgements``
exercise each condition.

In this codebase abilities are not stored in a separate ``ABILITY_CONF``
table; they are ``SKILL_CONF.json`` rows referenced through
``pet_feature``.  Therefore ``evidence.source_table`` is restricted to
``SKILL_CONF`` for the two evidence-bearing statuses; ``confirmed_ignored``
and ``evidence_missing`` allow ``None`` (no evidence).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_RULES_PATH = (
    ROOT / "roco" / "compiler" / "rules" / "effect_gap_acknowledgements.jsonl"
)
DEFAULT_PAK_DATA = ROOT / "pak-public-kit" / "output" / "data" / "BinData"


ALLOWED_STATUSES: tuple[str, ...] = (
    "evidence_available_deferred",
    "evidence_available_weak",
    "evidence_missing",
    "confirmed_ignored",
)

# Per-status allowed values for ``evidence.source_table``.  ``None`` means
# the row is permitted to omit the ``evidence`` block entirely.
ALLOWED_SOURCE_TABLES: dict[str, tuple[str | None, ...]] = {
    "evidence_available_deferred": ("SKILL_CONF",),
    "evidence_available_weak": ("SKILL_CONF",),
    "evidence_missing": (None,),
    "confirmed_ignored": ("SKILL_CONF", "BUFF_CONF", "EFFECT_CONF", None),
}

ALLOWED_GAP_SOURCE_TYPES: tuple[str, ...] = ("skill", "ability")

REQUIRED_GAP_MATCH_FIELDS: tuple[str, ...] = (
    "source_type",
    "source_name",
    "primitive",
    "timing_code",
    "reason",
    "params",
)

PAK_FILE_BY_TABLE: dict[str, str] = {
    "SKILL_CONF": "SKILL_CONF.json",
    "BUFF_CONF": "BUFF_CONF.json",
    "EFFECT_CONF": "EFFECT_CONF.json",
}


@dataclass(frozen=True)
class Acknowledgement:
    gap_match: dict
    audit: dict
    status: str
    evidence: dict | None
    owner: str
    note: str
    weak_reason: str | None
    probe_summary: str | None
    ignored_reason: str | None
    allow_multi_match: bool
    expected_matches: list[dict]
    allow_stale: bool
    stale_reason: str | None
    line_no: int

    @property
    def canonical_key(self) -> str:
        return canonical_gap_key(self.gap_match)

    @property
    def expected_canonical_keys(self) -> list[str]:
        if self.allow_multi_match:
            return [canonical_gap_key(m) for m in self.expected_matches]
        return [self.canonical_key]


def _stable_params_hash(params: Any) -> str:
    """Deterministic short digest of a JSON-serialisable params object."""
    serialised = json.dumps(params, sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(serialised.encode("utf-8")).hexdigest()[:12]


def canonical_gap_key(gap_match: dict) -> str:
    """Build a canonical key from a ``gap_match`` block.

    Mirrors the ``effect_gaps`` natural-key shape:
    ``source_type | source_name | primitive | timing_code | reason | hash(params)``.
    Two acks collide iff they point at the same logical gap row, which is
    exactly what the loader and validation guards want to detect.
    """
    parts = [
        str(gap_match["source_type"]),
        str(gap_match["source_name"]),
        str(gap_match["primitive"]),
        str(gap_match.get("timing_code")),
        str(gap_match["reason"]),
        _stable_params_hash(gap_match.get("params", {})),
    ]
    return "|".join(parts)


def canonical_gap_key_from_row(row: dict) -> str:
    """Build a canonical key from a ``effect_gaps`` DB row dict.

    Accepts either ``params`` (dict) or ``params_json`` (str) so it can be
    used directly with sqlite3 row factories or already-parsed snapshots.
    """
    params = row.get("params")
    if params is None:
        params = json.loads(row.get("params_json") or "{}")
    return canonical_gap_key({
        "source_type": row["source_type"],
        "source_name": row["source_name"],
        "primitive": row["primitive"],
        "timing_code": row.get("timing_code"),
        "reason": row["reason"],
        "params": params,
    })


def _load_pak_table(path: Path) -> dict[int, dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data.get("RocoDataRows", data)
    return {int(k): v for k, v in rows.items()}


class _PakAccessor:
    """Lazy in-process cache for pak tables, keyed by directory + table name."""

    def __init__(self, pak_dir: Path, overrides: dict[str, dict[int, dict]] | None) -> None:
        self._pak_dir = pak_dir
        self._overrides = overrides or {}
        self._cache: dict[str, dict[int, dict]] = {}

    def get(self, table: str) -> dict[int, dict]:
        if table in self._overrides:
            return self._overrides[table]
        if table not in self._cache:
            file_name = PAK_FILE_BY_TABLE.get(table)
            if file_name is None:
                raise RuntimeError(f"no pak file mapping for table {table!r}")
            self._cache[table] = _load_pak_table(self._pak_dir / file_name)
        return self._cache[table]


def load_acknowledgements(
    rules_path: Path | None = None,
    pak_tables: dict[str, dict[int, dict]] | None = None,
    pak_dir: Path | None = None,
    known_family_keys: set[str] | None = None,
) -> list[Acknowledgement]:
    """Parse + strictly validate the acknowledgements JSONL file.

    Parameters mirror :func:`load_buff_immunity_table`: ``rules_path`` and
    ``pak_tables`` are injectable so tests drive the loader from
    ``tmp_path`` + stub pak tables.  ``known_family_keys`` is optional;
    when provided, the loader cross-checks ``audit.family_key`` against
    the known family catalog and rejects unknown values.
    """
    path = rules_path if rules_path is not None else DEFAULT_RULES_PATH
    accessor = _PakAccessor(pak_dir or DEFAULT_PAK_DATA, pak_tables)

    acks: list[Acknowledgement] = []
    seen_keys: dict[str, int] = {}
    if not path.exists():
        return acks
    with path.open("r", encoding="utf-8") as fp:
        for line_no, raw in enumerate(fp, 1):
            raw = raw.strip()
            if not raw or raw.startswith("#"):
                continue
            try:
                rec = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise RuntimeError(
                    f"effect_gap_acknowledgements.jsonl line {line_no}: invalid JSON: {exc}"
                ) from exc
            ack = _validate_row(rec, line_no, accessor, known_family_keys)
            # 4. duplicate canonical key
            for key in ack.expected_canonical_keys:
                if key in seen_keys:
                    raise RuntimeError(
                        f"effect_gap_acknowledgements.jsonl line {line_no}: "
                        f"duplicate gap canonical key (already claimed on line "
                        f"{seen_keys[key]})"
                    )
                seen_keys[key] = line_no
            acks.append(ack)
    return acks


def _require_str(value: Any, line_no: int, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise RuntimeError(
            f"effect_gap_acknowledgements.jsonl line {line_no}: {name} must be a non-empty string"
        )
    return value


def _validate_row(
    rec: Any,
    line_no: int,
    accessor: _PakAccessor,
    known_family_keys: set[str] | None,
) -> Acknowledgement:
    if not isinstance(rec, dict):
        raise RuntimeError(
            f"effect_gap_acknowledgements.jsonl line {line_no}: row must be a JSON object"
        )

    # 1. status
    status = rec.get("status")
    if status not in ALLOWED_STATUSES:
        raise RuntimeError(
            f"effect_gap_acknowledgements.jsonl line {line_no}: unknown status "
            f"{status!r}; allowed {ALLOWED_STATUSES}"
        )

    # 3. gap_match shape
    gap_match = rec.get("gap_match")
    if not isinstance(gap_match, dict):
        raise RuntimeError(
            f"effect_gap_acknowledgements.jsonl line {line_no}: gap_match must be an object"
        )
    missing = [k for k in REQUIRED_GAP_MATCH_FIELDS if k not in gap_match]
    if missing:
        raise RuntimeError(
            f"effect_gap_acknowledgements.jsonl line {line_no}: gap_match missing "
            f"required fields {missing}"
        )
    if not isinstance(gap_match["params"], dict):
        raise RuntimeError(
            f"effect_gap_acknowledgements.jsonl line {line_no}: gap_match.params must be an object"
        )
    if gap_match["source_type"] not in ALLOWED_GAP_SOURCE_TYPES:
        raise RuntimeError(
            f"effect_gap_acknowledgements.jsonl line {line_no}: gap_match.source_type "
            f"{gap_match['source_type']!r} not in {ALLOWED_GAP_SOURCE_TYPES}; add a "
            f"loader branch if a new consumer kind is introduced"
        )

    # 2. evidence.source_table allowed for this status
    evidence = rec.get("evidence")
    source_table = evidence.get("source_table") if isinstance(evidence, dict) else None
    allowed_tables = ALLOWED_SOURCE_TABLES[status]
    if source_table not in allowed_tables:
        raise RuntimeError(
            f"effect_gap_acknowledgements.jsonl line {line_no}: evidence.source_table "
            f"{source_table!r} not allowed for status {status!r}; allowed {allowed_tables}"
        )

    # 8/9/10. status-specific required fields
    weak_reason = rec.get("weak_reason")
    probe_summary = rec.get("probe_summary")
    ignored_reason = rec.get("ignored_reason")
    if status == "evidence_available_weak":
        _require_str(weak_reason, line_no, "weak_reason")
    if status == "evidence_missing":
        _require_str(probe_summary, line_no, "probe_summary")
    if status == "confirmed_ignored":
        _require_str(ignored_reason, line_no, "ignored_reason")

    # 5/6/7/13. evidence + desc + direct-reference checks
    if status in ("evidence_available_deferred", "evidence_available_weak"):
        if not isinstance(evidence, dict):
            raise RuntimeError(
                f"effect_gap_acknowledgements.jsonl line {line_no}: status {status!r} "
                f"requires an evidence object"
            )
        _validate_evidence_against_pak(
            evidence, gap_match, status, line_no, accessor
        )

    # 11. audit.family_key cross-check (optional — only when catalog supplied)
    audit = rec.get("audit") or {}
    if not isinstance(audit, dict):
        raise RuntimeError(
            f"effect_gap_acknowledgements.jsonl line {line_no}: audit must be an object"
        )
    family_key = audit.get("family_key")
    if known_family_keys is not None:
        if not isinstance(family_key, str) or family_key not in known_family_keys:
            raise RuntimeError(
                f"effect_gap_acknowledgements.jsonl line {line_no}: audit.family_key "
                f"{family_key!r} not present in the effect-family catalog"
            )

    # 12. allow_multi_match constraints
    allow_multi_match = bool(rec.get("allow_multi_match", False))
    expected_matches_raw = rec.get("expected_matches")
    if allow_multi_match:
        if not isinstance(expected_matches_raw, list) or not expected_matches_raw:
            raise RuntimeError(
                f"effect_gap_acknowledgements.jsonl line {line_no}: allow_multi_match=true "
                f"requires a non-empty expected_matches list"
            )
        expected_matches: list[dict] = []
        for idx, em in enumerate(expected_matches_raw):
            if not isinstance(em, dict):
                raise RuntimeError(
                    f"effect_gap_acknowledgements.jsonl line {line_no}: expected_matches[{idx}] "
                    f"must be an object"
                )
            for k in REQUIRED_GAP_MATCH_FIELDS:
                if k not in em:
                    raise RuntimeError(
                        f"effect_gap_acknowledgements.jsonl line {line_no}: "
                        f"expected_matches[{idx}] missing field {k!r}"
                    )
            expected_matches.append(em)
    else:
        if expected_matches_raw is not None:
            raise RuntimeError(
                f"effect_gap_acknowledgements.jsonl line {line_no}: expected_matches must be "
                f"omitted when allow_multi_match is false"
            )
        expected_matches = []

    allow_stale = bool(rec.get("allow_stale", False))
    stale_reason = rec.get("stale_reason")
    if allow_stale:
        _require_str(stale_reason, line_no, "stale_reason")

    return Acknowledgement(
        gap_match=gap_match,
        audit=audit,
        status=status,
        evidence=evidence if isinstance(evidence, dict) else None,
        owner=str(rec.get("owner", "")),
        note=str(rec.get("note", "")),
        weak_reason=weak_reason if isinstance(weak_reason, str) else None,
        probe_summary=probe_summary if isinstance(probe_summary, str) else None,
        ignored_reason=ignored_reason if isinstance(ignored_reason, str) else None,
        allow_multi_match=allow_multi_match,
        expected_matches=expected_matches,
        allow_stale=allow_stale,
        stale_reason=stale_reason if isinstance(stale_reason, str) else None,
        line_no=line_no,
    )


def _validate_evidence_against_pak(
    evidence: dict,
    gap_match: dict,
    status: str,
    line_no: int,
    accessor: _PakAccessor,
) -> None:
    source_table = evidence["source_table"]
    source_id = evidence.get("source_id")
    desc_quote = evidence.get("desc_quote")
    anchor_keywords = evidence.get("anchor_keywords")

    if not isinstance(source_id, int):
        raise RuntimeError(
            f"effect_gap_acknowledgements.jsonl line {line_no}: evidence.source_id must be int"
        )

    pak_table = accessor.get(source_table)
    pak_row = pak_table.get(source_id)
    if pak_row is None:
        raise RuntimeError(
            f"effect_gap_acknowledgements.jsonl line {line_no}: evidence.source_id "
            f"{source_id} not present in {source_table}"
        )

    real_desc = str(pak_row.get("desc", ""))
    if not isinstance(desc_quote, str) or desc_quote != real_desc:
        raise RuntimeError(
            f"effect_gap_acknowledgements.jsonl line {line_no}: evidence.desc_quote "
            f"does not match {source_table}[{source_id}].desc verbatim"
        )

    if not isinstance(anchor_keywords, list):
        raise RuntimeError(
            f"effect_gap_acknowledgements.jsonl line {line_no}: anchor_keywords must be a list"
        )
    # 6. strong status requires non-empty anchors
    if status == "evidence_available_deferred" and not anchor_keywords:
        raise RuntimeError(
            f"effect_gap_acknowledgements.jsonl line {line_no}: status "
            f"evidence_available_deferred requires non-empty anchor_keywords"
        )
    # 7. every anchor must appear in desc_quote
    for kw in anchor_keywords:
        if not isinstance(kw, str) or not kw:
            raise RuntimeError(
                f"effect_gap_acknowledgements.jsonl line {line_no}: anchor_keywords entries "
                f"must be non-empty strings"
            )
        if kw not in desc_quote:
            raise RuntimeError(
                f"effect_gap_acknowledgements.jsonl line {line_no}: anchor keyword "
                f"{kw!r} is not a substring of desc_quote"
            )

    # 13. direct-reference: name + skill_result references gap token
    real_name = str(pak_row.get("name", ""))
    if real_name != gap_match["source_name"]:
        raise RuntimeError(
            f"effect_gap_acknowledgements.jsonl line {line_no}: {source_table}[{source_id}] "
            f"name {real_name!r} does not match gap_match.source_name "
            f"{gap_match['source_name']!r}"
        )
    params = gap_match["params"]
    # The consuming row's skill_result holds either effect_ids (for EFFECT_CONF
    # primitives) or buff_ids (for direct BUFF_CONF references — pak reuses
    # the ``effect_id`` slot in both cases).
    target_id = params.get("effect_id") or params.get("buff_id")
    if target_id is None:
        raise RuntimeError(
            f"effect_gap_acknowledgements.jsonl line {line_no}: gap_match.params lacks both "
            f"effect_id and buff_id; cannot verify direct reference"
        )
    skill_result = pak_row.get("skill_result") or pak_row.get("effect_list") or []
    referenced_ids = {
        int(entry.get("effect_id", 0))
        for entry in skill_result
        if isinstance(entry, dict) and entry.get("effect_id") is not None
    }
    if int(target_id) not in referenced_ids:
        raise RuntimeError(
            f"effect_gap_acknowledgements.jsonl line {line_no}: {source_table}[{source_id}]."
            f"skill_result does not reference id {target_id}; this evidence row is "
            f"unrelated to the declared gap_match"
        )
