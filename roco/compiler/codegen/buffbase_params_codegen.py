"""Codegen for ``roco/generated/buffbase_params.py``.

Reads ``BUFFBASE_CONF.json`` and emits a runtime-accessible Python
module with three flat dicts keyed by ``base_id``:

* ``BUFFBASE_PARAMS[base_id]`` — the full ``buffbase_param`` payload
  as an int tuple.  Multi-element slot lists are kept as nested
  tuples so the kernel can read either ``params[0]`` (scalar) or
  ``params[0][0]`` (sub-element) without re-parsing JSON at runtime.
* ``BUFFBASE_ORDER[base_id]`` — pak ``buffbase_order`` (proto
  ``BuffType``).  Equivalent to ``base_id // 1000`` for clean prefixes
  but pulled from the actual record so mixed-prefix outliers carry
  their true order.
* ``BUFFBASE_TRIGGER_TYPE[base_id]`` — pak ``trigger_type`` (or 0 when
  the JSON omits it; proto encodes missing as null).

Storing this side-table at compile time lets handlers read the raw pak
params at runtime instead of relying on hand-baked kernel constants —
the architectural shift requested in Phase 8.  The kernel row format
stays an 8-tuple; the new dicts are looked up by ``row[ROW_ARG0]``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
PAK_DATA = ROOT / "pak-public-kit" / "output" / "data" / "BinData"
GEN_DIR = ROOT / "roco" / "generated"
BUFFBASE_PARAMS_PATH = GEN_DIR / "buffbase_params.py"


def _normalize_slot(slot: Any) -> tuple[int, ...] | int:
    """Coerce one ``buffbase_param[i]`` entry into a scalar or int tuple.

    Pak stores each slot as ``{"params": [v]}`` for scalar and
    ``{"params": [v1, v2, ...]}`` for multi-element.  We collapse the
    common scalar case to a bare int for handler ergonomics — most
    slots are scalar and `params[i]` reads cleaner than `params[i][0]`.
    Multi-element stays as a tuple so the shape is preserved.
    """
    if isinstance(slot, dict):
        inner = slot.get("params") or []
    elif isinstance(slot, list):
        inner = slot
    else:
        inner = [slot]
    if len(inner) == 1:
        return int(inner[0])
    return tuple(int(v) for v in inner)


def _record_param_tuple(rec: dict) -> tuple:
    """Render one BUFFBASE_CONF record's ``buffbase_param`` as a tuple."""
    raw = rec.get("buffbase_param") or rec.get("params") or []
    return tuple(_normalize_slot(slot) for slot in raw)


def _load_pak_table(path: Path) -> dict[int, dict]:
    with path.open("r", encoding="utf-8") as fp:
        data = json.load(fp)
    rows = data.get("RocoDataRows", data)
    return {int(k): v for k, v in rows.items()}


def build_buffbase_tables(pak_data_dir: Path = PAK_DATA) -> dict[str, dict[int, Any]]:
    """Return the three dicts in their final flat form."""
    rows = _load_pak_table(pak_data_dir / "BUFFBASE_CONF.json")
    params: dict[int, tuple] = {}
    order: dict[int, int] = {}
    trigger: dict[int, int] = {}
    for bid, rec in rows.items():
        params[bid] = _record_param_tuple(rec)
        order[bid] = int(rec.get("buffbase_order") or 0)
        # JSON omits ``trigger_type`` when null; preserve 0 as the
        # "no trigger" sentinel so consumers can always dict-get safely.
        trigger[bid] = int(rec.get("trigger_type") or 0)
    return {"params": params, "order": order, "trigger": trigger}


def _render(tables: dict[str, dict[int, Any]]) -> str:
    """Render the generated module.  Sorted keys for byte stability."""
    lines: list[str] = [
        "# Auto-generated from BUFFBASE_CONF.json — do not edit.",
        "# Regenerate with: uv run python -m roco.compiler.gen_prefix_map",
        "",
        '"""Runtime catalog of pak BUFFBASE_CONF parameters.',
        "",
        "Handlers read ``BUFFBASE_PARAMS[base_id]`` to get the literal",
        "values pak configured for each buff_base_id (stat indices,",
        "magnitudes, durations) instead of relying on hand-baked",
        "kernel constants.  Storing every record at compile time keeps",
        "runtime free of JSON access and lets the kernel stay pure-",
        "tuple in its hot loop.",
        '"""',
        "",
        "from typing import Any",
        "",
        "BUFFBASE_PARAMS: dict[int, tuple] = {",
    ]
    for bid in sorted(tables["params"]):
        lines.append(f"    {bid}: {tables['params'][bid]!r},")
    lines.append("}")
    lines.append("")
    lines.append("BUFFBASE_ORDER: dict[int, int] = {")
    for bid in sorted(tables["order"]):
        lines.append(f"    {bid}: {tables['order'][bid]},")
    lines.append("}")
    lines.append("")
    lines.append("BUFFBASE_TRIGGER_TYPE: dict[int, int] = {")
    for bid in sorted(tables["trigger"]):
        lines.append(f"    {bid}: {tables['trigger'][bid]},")
    lines.append("}")
    lines.append("")
    return "\n".join(lines)


def write_buffbase_params(pak_data_dir: Path = PAK_DATA) -> int:
    """Codegen entry point: build, render, write.  Returns row count."""
    tables = build_buffbase_tables(pak_data_dir)
    BUFFBASE_PARAMS_PATH.write_text(_render(tables), encoding="utf-8")
    return len(tables["params"])
