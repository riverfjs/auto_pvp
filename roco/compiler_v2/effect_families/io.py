"""pak / canonical record / compiler semantic loaders.

No behavioural reuse from :mod:`roco.data` — these helpers read directly
from disk so the family catalog stays buildable as a static artifact.
"""

from __future__ import annotations

from pathlib import Path

import json

from roco.data.canonical import canonical_list

from .paths import PAK_DATA


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
    return canonical_list(name)


def _load_exact_rules() -> set[int]:
    """Return exact_emit_ids.

    Exact effect_id semantics have been migrated to pak family decoders;
    the family catalog keeps this hook only for generated exact emitters
    such as weather rows.
    """

    return set()
