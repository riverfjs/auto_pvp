"""Codegen for ``roco/generated/pak_rules.py``.

Extracts a small set of pak-derivable game-rule constants from
``BATTLE_GLOBAL_CONFIG.json``.  Only constants whose semantics match
pak's encoding are listed; kernel-specific composites stay in
``common/constants.py``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PAK_DATA = ROOT / "pak-public-kit" / "output" / "data" / "BinData"
GEN_DIR = ROOT / "roco" / "generated"
PAK_RULES_PATH = GEN_DIR / "pak_rules.py"


# Map our constant name -> pak BATTLE_GLOBAL_CONFIG key.
# Only constants whose semantics match pak's encoding are listed here.
# Kernel-specific composites (e.g. TYPE_DOUBLE_RESIST_BPS from multiplicative
# stack of two single-resist mults) stay in common/constants.py.
_PAK_RULES_KEYS = {
    "TYPE_NEUTRAL_BPS":        "restraint_percent",
    "TYPE_WEAK_BPS":           "double_restraint_percent",
    "TYPE_DOUBLE_WEAK_BPS":    "triple_restraint_percent",
    "TYPE_RESIST_BPS":         "restrained_percent",
    # ``double_restrained_percent`` in pak = 7500 BPS (0.75×), used by the
    # kernel as the multiplier when both defender types resist the move.
    # The previous hand-coded value was 3333 (1/3×), which deliberately
    # differed from pak; restore pak truth as the source.
    "TYPE_DOUBLE_RESIST_BPS":  "double_restrained_percent",
    "DAMAGE_PERCENT_LIMIT":    "damage_percent_limit",
    "SKILL_DAMAGE_MAX":        "skill_damage_max",
    "PVP_LEVEL":               "battle_pvp_level",
}


def load_pak_rules(pak_data_dir: Path = PAK_DATA) -> tuple[dict[str, int], list[str]]:
    """Return ``(constants, missing)`` from BATTLE_GLOBAL_CONFIG.

    ``missing`` lists ``const (pak_key)`` strings whose values are absent
    or non-numeric in pak; caller decides whether to warn.
    """
    p = pak_data_dir / "BATTLE_GLOBAL_CONFIG.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    rows = data.get("RocoDataRows", data)
    by_key = {v.get("key"): v.get("num") for v in rows.values() if v.get("key")}

    out: dict[str, int] = {}
    missing: list[str] = []
    for const, pak_key in _PAK_RULES_KEYS.items():
        val = by_key.get(pak_key)
        if isinstance(val, (int, float)):
            out[const] = int(val)
        else:
            missing.append(f"{const} ({pak_key})")
    return out, missing


def render(out: dict[str, int]) -> str:
    lines = [
        "# Auto-generated from BATTLE_GLOBAL_CONFIG.json — do not edit.",
        "# Regenerate with: uv run python -m roco.compiler.gen_prefix_map",
        "",
    ]
    for k, v in out.items():
        lines.append(f"{k} = {v}")
    lines.append("")
    return "\n".join(lines)


def write_pak_rules_table(pak_data_dir: Path = PAK_DATA) -> dict[str, int]:
    out, missing = load_pak_rules(pak_data_dir)
    PAK_RULES_PATH.write_text(render(out), encoding="utf-8")
    if missing:
        print(f"WARNING: pak_rules missing values for: {missing}", file=sys.stderr)
    return out
