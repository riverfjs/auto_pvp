"""Codegen for ``roco/generated/pak_ops.py``.

Emits ``PAK_PREFIX_NAMES`` — debug/audit names for every pak buff prefix
that appears in ``BUFF_CONF.json``.  Aliases come from both rule files
so the alias table stays exhaustive post-7C, when most prefixes
migrated from ``prefix_handlers.jsonl`` to
``buffbase_order_handlers.jsonl``:

* Legacy axis: ``rules/prefix_handlers.jsonl`` — covers the few mixed
  prefixes that did not migrate.
* Pak axis: ``rules/buffbase_order_handlers.jsonl`` — aliases keyed by
  ``buffbase_order``; mapped onto the nominal prefix via the
  ``prefix = 2000 + buffbase_order`` identity that holds across all
  current rules.

Unseen prefixes get a generic ``PREFIX_<n>`` label so the table stays
exhaustive.
"""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PAK_DATA = ROOT / "pak-public-kit" / "output" / "data" / "BinData"
GEN_DIR = ROOT / "roco" / "generated"
RULES_DIR = ROOT / "roco" / "compiler" / "rules"
PREFIX_SEED_PATH = RULES_DIR / "prefix_handlers.jsonl"
BUFFBASE_ORDER_SEED_PATH = RULES_DIR / "buffbase_order_handlers.jsonl"
PAK_OPS_PATH = GEN_DIR / "pak_ops.py"


def load_aliases() -> dict[int, str]:
    """Collect prefix-display aliases from both rule files.

    A ``buffbase_order_handlers.jsonl`` row's alias is associated with
    the prefix ``2000 + buffbase_order`` (the structural identity that
    holds across every current rule).  Legacy ``prefix_handlers.jsonl``
    aliases override the buffbase_order ones when both refer to the
    same prefix, since the mixed-prefix case is where the prefix axis
    still owns the dispatch.
    """
    aliases: dict[int, str] = {}
    if BUFFBASE_ORDER_SEED_PATH.exists():
        with BUFFBASE_ORDER_SEED_PATH.open("r", encoding="utf-8") as fp:
            for raw in fp:
                raw = raw.strip()
                if not raw or raw.startswith("#"):
                    continue
                rec = json.loads(raw)
                if "buffbase_order" in rec and rec.get("alias"):
                    aliases[2000 + int(rec["buffbase_order"])] = rec["alias"]
    with PREFIX_SEED_PATH.open("r", encoding="utf-8") as fp:
        for raw in fp:
            raw = raw.strip()
            if not raw or raw.startswith("#"):
                continue
            rec = json.loads(raw)
            if "prefix" in rec and rec.get("alias"):
                aliases[int(rec["prefix"])] = rec["alias"]
    return aliases


def collect_prefixes(pak_data_dir: Path = PAK_DATA) -> set[int]:
    buff_path = pak_data_dir / "BUFF_CONF.json"
    rows = json.loads(buff_path.read_text(encoding="utf-8")).get("RocoDataRows", {})
    all_prefixes: set[int] = set()
    for rec in rows.values():
        for bid in rec.get("buff_base_ids") or []:
            if bid:
                all_prefixes.add(bid // 1000)
    return all_prefixes


def render(aliases: dict[int, str], all_prefixes: set[int]) -> str:
    lines = [
        "# Auto-generated from BUFF_CONF.json + prefix_handlers.jsonl — do not edit.",
        "# Regenerate with: uv run python -m roco.compiler.gen_prefix_map",
        "",
        "# Synthetic ``EFFECT_CONF.type`` markers (not pak buff prefixes).",
        "EFF_BUFF_APPLY = 10001",
        "EFF_DAMAGE = 10002",
        "EFF_STATE_CHANGE = 10003",
        "",
        "PAK_PREFIX_NAMES: dict[int, str] = {",
    ]
    for pfx in sorted(all_prefixes):
        name = aliases.get(pfx, f"PREFIX_{pfx}")
        lines.append(f"    {pfx}: {name!r},")
    lines.append("}")
    lines.append("")
    return "\n".join(lines)


def write_pak_ops_table(pak_data_dir: Path = PAK_DATA) -> int:
    aliases = load_aliases()
    all_prefixes = collect_prefixes(pak_data_dir)
    PAK_OPS_PATH.write_text(render(aliases, all_prefixes), encoding="utf-8")
    return len(all_prefixes)
