"""pak / canonical JSONL / exact_effects file loaders.

No behavioural reuse from :mod:`roco.data` — these helpers read directly
from disk so the family catalog stays buildable without going through
``build_db`` first.
"""

from __future__ import annotations

import json
from pathlib import Path

from .paths import CANONICAL_DIR, EXACT_RULES_PATH, PAK_DATA


def _load_pak_table(path: Path) -> dict[int, dict]:
    with path.open("r", encoding="utf-8") as fp:
        data = json.load(fp)
    rows = data.get("RocoDataRows", data)
    return {int(k): v for k, v in rows.items()}


def _load_desc_notes() -> dict[int, str]:
    """Read DESC_NOTE_CONF.json directly (no parse_pak import)."""
    rows = _load_pak_table(PAK_DATA / "BinData" / "DESC_NOTE_CONF.json")
    return {int(k): str(rec.get("note", "")) for k, rec in rows.items()}


def _load_canonical(name: str) -> list[dict]:
    path = CANONICAL_DIR / name
    if not path.exists():
        return []
    out: list[dict] = []
    with path.open("r", encoding="utf-8") as fp:
        for raw in fp:
            raw = raw.strip()
            if raw:
                out.append(json.loads(raw))
    return out


def _load_exact_rules() -> tuple[set[int], set[int]]:
    """Return (exact_emit_ids, exact_ignored_ids) from the JSONL source."""
    emit: set[int] = set()
    ignored: set[int] = set()
    with EXACT_RULES_PATH.open("r", encoding="utf-8") as fp:
        for raw in fp:
            raw = raw.strip()
            if not raw or raw.startswith("#"):
                continue
            rec = json.loads(raw)
            eid = int(rec["effect_id"])
            if rec.get("kind", "emit") == "ignored":
                ignored.add(eid)
            else:
                emit.add(eid)
    return emit, ignored
