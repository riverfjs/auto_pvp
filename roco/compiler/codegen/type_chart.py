"""Codegen for ``roco/generated/type_chart.py``.

Reads ``TYPE_DICTIONARY.json`` (one row per element with sparse
``type_restraint{N}`` fields) and emits a dense ``TYPE_CHART_BPS``
single-defender BPS table the kernel indexes by ``(attacker_id, defender_id)``.

Depends on ``roco/generated/pak_rules.py`` already existing
(``TYPE_NEUTRAL_BPS`` / ``TYPE_WEAK_BPS`` / ``TYPE_RESIST_BPS`` are
sourced from there).  ``gen_prefix_map.main`` runs ``pak_rules`` before
``type_chart`` for this reason.
"""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PAK_DATA = ROOT / "pak-public-kit" / "output" / "data" / "BinData"
GEN_DIR = ROOT / "roco" / "generated"
TYPE_CHART_PATH = GEN_DIR / "type_chart.py"


def build_chart(pak_data_dir: Path = PAK_DATA) -> tuple[list[list[int]], list[str]]:
    """Return ``(chart, element_names)``.

    ``TYPE_DICTIONARY.json`` carries one row per element with sparse
    ``type_restraint{N}`` fields:

    * ``+1`` → this element deals super-effective damage to element N
      (``TYPE_WEAK_BPS`` = 20000 = 2.0×).
    * ``-1`` → this element is resisted by element N
      (``TYPE_RESIST_BPS`` = 5000 = 0.5×).
    * missing → neutral (``TYPE_NEUTRAL_BPS`` = 10000 = 1.0×).

    Dual-type composition (3.0× / 0.25× overlap rules) is handled by the
    kernel at runtime against the single-defender values in this table.

    Rows are emitted in the kernel's :data:`ELEMENT_NAMES` order so
    ``TYPE_CHART_BPS[attacker_id][defender_id]`` indexes directly with
    the element ids that show up in :class:`hot.PETS`.
    """
    from roco.common.enums import ELEMENT_NAMES
    from roco.generated.pak_rules import (
        TYPE_NEUTRAL_BPS,
        TYPE_RESIST_BPS,
        TYPE_WEAK_BPS,
    )

    rows = json.loads((pak_data_dir / "TYPE_DICTIONARY.json").read_text(encoding="utf-8"))
    pak_rows = rows.get("RocoDataRows", rows)

    by_short_name: dict[str, dict] = {}
    for rec in pak_rows.values():
        short = rec.get("short_name")
        if short:
            by_short_name[short] = rec

    n = len(ELEMENT_NAMES)
    pak_ids_in_order: list[int] = []
    for name in ELEMENT_NAMES:
        rec = by_short_name.get(name)
        if rec is None:
            raise RuntimeError(f"TYPE_DICTIONARY missing short_name={name!r}")
        pak_ids_in_order.append(int(rec["id"]))

    chart: list[list[int]] = [[TYPE_NEUTRAL_BPS] * n for _ in range(n)]
    for attacker_idx, attacker_name in enumerate(ELEMENT_NAMES):
        rec = by_short_name[attacker_name]
        for defender_idx, defender_pak_id in enumerate(pak_ids_in_order):
            sign = rec.get(f"type_restraint{defender_pak_id}", 0)
            if sign == 1:
                chart[attacker_idx][defender_idx] = TYPE_WEAK_BPS
            elif sign == -1:
                chart[attacker_idx][defender_idx] = TYPE_RESIST_BPS

    return chart, list(ELEMENT_NAMES)


def render(chart: list[list[int]], element_names: list[str]) -> str:
    n = len(element_names)
    lines = [
        "# Auto-generated from TYPE_DICTIONARY.json — do not edit.",
        "# Regenerate with: uv run python -m roco.compiler.gen_prefix_map",
        "",
        f"# Element order matches roco.common.enums.ELEMENT_NAMES (length {n}).",
        "TYPE_CHART_BPS: tuple[tuple[int, ...], ...] = (",
    ]
    for attacker_idx, attacker_name in enumerate(element_names):
        row_str = ", ".join(str(v) for v in chart[attacker_idx])
        lines.append(f"    ({row_str}),  # {attacker_idx:2d} {attacker_name}")
    lines.append(")")
    lines.append("")
    return "\n".join(lines)


def write_type_chart(pak_data_dir: Path = PAK_DATA) -> int:
    chart, element_names = build_chart(pak_data_dir)
    TYPE_CHART_PATH.write_text(render(chart, element_names), encoding="utf-8")
    return len(element_names)
