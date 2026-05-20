"""Codegen for the ``buffbase_order`` axis of the buff handler map.

Reads the editable seed (``rules/buffbase_order_handlers.jsonl``) —
``BUFFBASE_CONF.buffbase_order → handler`` — and joins it with the
live ``BUFFBASE_CONF.json`` to pre-resolve every base_id whose order
appears in the seed.  The result is a ``base_id → handler_idx`` map
embedded into :data:`prefix_handler_map.json` under the
``base_id_via_order_map`` key, so the runtime classifier can do a
single dict lookup without needing BUFFBASE_CONF at import time.

Family axes (this module is the second-tier lookup after exact
``base_id_map`` and before the legacy ``prefix_map``) follow the same
pak-native discipline as
:mod:`roco.compiler.effect_codegen.family_axes`: the schema field
*itself* is the dispatch key, so we don't accumulate per-id rule rows
for ids that already share a pak-axis value.
"""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PAK_DATA = ROOT / "pak-public-kit" / "output" / "data" / "BinData"
RULES_DIR = ROOT / "roco" / "compiler" / "rules"
BUFFBASE_ORDER_SEED_PATH = RULES_DIR / "buffbase_order_handlers.jsonl"


def _load_seed(handler_indices: dict[str, int]) -> dict[int, int]:
    """Load the ``buffbase_order → handler_idx`` seed from JSONL.

    Each record carries ``buffbase_order``, ``handler``, and an optional
    ``alias`` (used only for human review — not stored in the binary
    map).  Unknown handler names raise so kernel renames cannot
    silently drop coverage; ``H_NOOP`` is rejected for the same reason
    as in :mod:`prefixes`.

    Duplicate ``buffbase_order`` keys with disagreeing handlers raise
    immediately — there is no defensible last-write-wins semantics for
    the family axis.
    """
    if not BUFFBASE_ORDER_SEED_PATH.exists():
        return {}
    seed: dict[int, int] = {}
    with BUFFBASE_ORDER_SEED_PATH.open("r", encoding="utf-8") as fp:
        for line_no, raw in enumerate(fp, 1):
            raw = raw.strip()
            if not raw or raw.startswith("#"):
                continue
            rec = json.loads(raw)
            order = int(rec["buffbase_order"])
            handler_name = rec["handler"]
            if handler_name == "H_NOOP":
                raise RuntimeError(
                    f"buffbase_order_handlers.jsonl line {line_no}: "
                    f"H_NOOP is forbidden — drop the row so the order "
                    f"surfaces as an audit gap, or pick a real handler"
                )
            if handler_name not in handler_indices:
                raise RuntimeError(
                    f"buffbase_order_handlers.jsonl line {line_no}: "
                    f"unknown handler '{handler_name}' "
                    f"(not in handler_indices)"
                )
            handler_idx = handler_indices[handler_name]
            if order in seed and seed[order] != handler_idx:
                raise RuntimeError(
                    f"buffbase_order_handlers.jsonl line {line_no}: "
                    f"duplicate buffbase_order={order} with conflicting "
                    f"handler"
                )
            seed[order] = handler_idx
    return seed


def build_base_id_via_order_map(
    handler_indices: dict[str, int],
    pak_data_dir: Path = PAK_DATA,
) -> dict[int, int]:
    """Join ``BUFFBASE_CONF`` with the seed to produce ``base_id → handler``.

    Every BUFFBASE_CONF row whose ``buffbase_order`` is in the seed
    appears in the output keyed by its own ``id``.  Rows whose order
    is *not* in the seed (or whose order is null/missing) are dropped
    here — they fall through to the legacy prefix map at runtime.
    """
    seed = _load_seed(handler_indices)
    if not seed:
        return {}
    buffbase_path = pak_data_dir / "BUFFBASE_CONF.json"
    with buffbase_path.open("r", encoding="utf-8") as fp:
        data = json.load(fp)
    rows = data.get("RocoDataRows", data)
    out: dict[int, int] = {}
    for bid_str, rec in rows.items():
        order_raw = rec.get("buffbase_order")
        if order_raw is None:
            continue
        h = seed.get(int(order_raw))
        if h is not None:
            out[int(bid_str)] = h
    return out


def seed_orders(handler_indices: dict[str, int]) -> set[int]:
    """Return the set of ``buffbase_order`` keys carried by the seed.

    Exposed so other codegen modules can compute "truly unmapped"
    families (a buffbase_order is mapped if it is in this set OR if
    its prefix has a rule in ``prefix_handlers.jsonl``).
    """
    return set(_load_seed(handler_indices).keys())
