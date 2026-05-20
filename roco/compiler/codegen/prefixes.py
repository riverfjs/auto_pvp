"""Codegen for ``roco/generated/prefix_handler_map.json``.

Builds the three-layer buff handler map that the runtime classifier
uses to resolve direct BUFF_CONF references:

1. ``base_id_map`` — hand-curated exact ``buff_base_id → handler``
   overrides (highest priority).
2. ``base_id_via_order_map`` — pak-axis resolution of
   ``BUFFBASE_CONF.buffbase_order → handler``, joined with
   BUFFBASE_CONF so the binary map is keyed directly by base_id (see
   :mod:`.buffbase_orders`).
3. ``prefix_map`` — legacy ``buff_base_id // 1000 → handler`` seed
   (lowest priority, covers the few prefixes whose buffbase_order
   distribution is not 100% concentrated and would otherwise lose
   their non-dominant base_ids).

The editable seeds are ``rules/prefix_handlers.jsonl`` (layers 1 + 3)
and ``rules/buffbase_order_handlers.jsonl`` (layer 2).
"""

from __future__ import annotations

import json
from pathlib import Path

from roco.compiler.codegen import buffbase_orders


ROOT = Path(__file__).resolve().parents[3]
PAK_DATA = ROOT / "pak-public-kit" / "output" / "data" / "BinData"
GEN_DIR = ROOT / "roco" / "generated"
RULES_DIR = ROOT / "roco" / "compiler" / "rules"
PREFIX_SEED_PATH = RULES_DIR / "prefix_handlers.jsonl"
PREFIX_MAP_PATH = GEN_DIR / "prefix_handler_map.json"


def _build_seed(h: dict[str, int]) -> tuple[dict[int, int], dict[int, int]]:
    """Load the hand-curated prefix / base_id → handler seed from JSONL.

    The JSONL is the editable source of truth for semantic decisions
    (which pak prefix family maps to which kernel handler).  Each record
    is either ``{"prefix": <int>, "handler": "H_*", "alias": "..."}`` or
    ``{"base_id": <int>, "handler": "H_*", "note": "..."}``.

    Unknown handler names raise immediately so renames in the kernel
    cannot silently drop a prefix from the seed.
    """
    prefix_seed: dict[int, int] = {}
    base_id_seed: dict[int, int] = {}
    with PREFIX_SEED_PATH.open("r", encoding="utf-8") as fp:
        for line_no, raw in enumerate(fp, 1):
            raw = raw.strip()
            if not raw or raw.startswith("#"):
                continue
            rec = json.loads(raw)
            handler_name = rec.get("handler")
            if handler_name == "H_NOOP":
                raise RuntimeError(
                    f"prefix_handlers.jsonl line {line_no}: ``handler: H_NOOP`` "
                    f"is forbidden — drop the row so the buff prefix surfaces "
                    f"as an audit gap, or add a real handler"
                )
            if handler_name not in h:
                raise RuntimeError(
                    f"prefix_handlers.jsonl line {line_no}: unknown handler "
                    f"'{handler_name}' (not in handler_indices)"
                )
            handler_idx = h[handler_name]
            if "prefix" in rec:
                prefix_seed[int(rec["prefix"])] = handler_idx
            elif "base_id" in rec:
                base_id_seed[int(rec["base_id"])] = handler_idx
            else:
                raise RuntimeError(
                    f"prefix_handlers.jsonl line {line_no}: record needs "
                    "either 'prefix' or 'base_id'"
                )
    return prefix_seed, base_id_seed


def build_prefix_map(handler_indices: dict[str, int], pak_data_dir: Path = PAK_DATA) -> dict:
    """Build the prefix_handler_map payload — does not write to disk.

    Output carries three lookup tables (see module docstring for the
    full layering rationale).  Stats track both axes so a future audit
    can spot a prefix that is unmapped at *both* layers — that's the
    real coverage hole worth surfacing, not "unmapped at the legacy
    prefix layer alone" which is the expected post-7C state for the
    88 clean prefixes migrated to buffbase_order.
    """
    prefix_seed, base_id_seed = _build_seed(handler_indices)
    base_id_via_order_map = buffbase_orders.build_base_id_via_order_map(
        handler_indices, pak_data_dir,
    )

    buff_path = pak_data_dir / "BUFF_CONF.json"
    with buff_path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    rows = data.get("RocoDataRows", data)

    all_prefixes: set[int] = set()
    all_base_ids: set[int] = set()
    for rec in rows.values():
        for bid in rec.get("buff_base_ids") or []:
            if bid:
                all_base_ids.add(bid)
                all_prefixes.add(bid // 1000)

    # Emit only prefixes that have a real handler (positive index).
    # Unmapped prefixes — including the families previously seeded with
    # ``handler: H_NOOP`` — are tracked in stats for visibility but not
    # written into ``prefix_map`` so downstream lookups can use a clean
    # "in map ⇔ has handler" invariant.
    prefix_map: dict[int, int] = {}
    for pfx in sorted(all_prefixes):
        if pfx in prefix_seed:
            prefix_map[pfx] = prefix_seed[pfx]

    # "Truly unmapped" = neither the prefix nor any base_id in that
    # prefix routes through the buffbase_order axis.  This is the
    # coverage hole the audit actually cares about, distinct from
    # "prefix migrated to buffbase_order".
    base_ids_by_prefix: dict[int, set[int]] = {}
    for bid in all_base_ids:
        base_ids_by_prefix.setdefault(bid // 1000, set()).add(bid)
    truly_unmapped: list[int] = []
    for pfx in sorted(all_prefixes):
        if pfx in prefix_map:
            continue
        if any(bid in base_id_via_order_map for bid in base_ids_by_prefix.get(pfx, ())):
            continue
        truly_unmapped.append(pfx)

    return {
        "prefix_map": {str(k): v for k, v in sorted(prefix_map.items())},
        "base_id_map": {str(k): v for k, v in sorted(base_id_seed.items())},
        "base_id_via_order_map": {
            str(k): v for k, v in sorted(base_id_via_order_map.items())
        },
        "stats": {
            "total_base_ids": len(all_base_ids),
            "total_prefixes": len(all_prefixes),
            "prefixes_in_legacy_map": len(prefix_map),
            "base_ids_via_order": len(base_id_via_order_map),
            "unmapped_prefixes": truly_unmapped,
        },
    }


def write_prefix_handler_map(handler_indices: dict[str, int]) -> dict:
    """Write ``prefix_handler_map.json`` and return the full payload."""
    result = build_prefix_map(handler_indices)
    PREFIX_MAP_PATH.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result
