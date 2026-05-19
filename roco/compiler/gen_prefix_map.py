"""Auto-generate handler indices + prefix->handler mapping.

Two outputs (both under roco/compiler/generated/):
  1. handler_indices.py  — H_* constants from handler_registry.json
  2. prefix_handler_map.json — prefix family -> handler index from BUFF_CONF

Run at build time:  uv run python -m roco.compiler.gen_prefix_map
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

from roco.compiler.effect_model import PakOp

ROOT = Path(__file__).resolve().parents[2]
PAK_DATA = ROOT / "pak-public-kit" / "output" / "data" / "BinData"
GEN_DIR = ROOT / "roco" / "compiler" / "generated"
REGISTRY_PATH = GEN_DIR / "handler_registry.json"
INDICES_PATH = GEN_DIR / "handler_indices.py"
ORDER_PATH = GEN_DIR / "handler_order.py"
PREFIX_MAP_PATH = GEN_DIR / "prefix_handler_map.json"

_OP_MODULES = (
    "roco.engine.kernel.op_mods",
    "roco.engine.kernel.op_resources",
    "roco.engine.kernel.op_marks",
    "roco.engine.kernel.op_status",
    "roco.engine.kernel.op_cute",
)


# ---------------------------------------------------------------------------
# Handler discovery + registry
# ---------------------------------------------------------------------------

def _discover_handlers() -> set[str]:
    names: set[str] = set()
    for mod_name in _OP_MODULES:
        mod = importlib.import_module(mod_name)
        for attr in dir(mod):
            if attr.startswith("op_") and callable(getattr(mod, attr)):
                names.add(attr)
    return names


def _load_registry() -> list[str]:
    if REGISTRY_PATH.exists():
        data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        return data["handlers"]
    return ["_noop"]


def _update_registry(existing: list[str], discovered: set[str]) -> list[str]:
    known = set(existing)
    new_handlers = sorted(discovered - known)
    return existing + new_handlers


def _save_registry(handlers: list[str]) -> None:
    data = {
        "_meta": {"version": 1, "description": "Append-only handler registry."},
        "handlers": handlers,
    }
    GEN_DIR.mkdir(parents=True, exist_ok=True)
    REGISTRY_PATH.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _func_to_const(name: str) -> str:
    if name == "_noop":
        return "H_NOOP"
    if name.startswith("op_"):
        return "H_" + name[3:].upper()
    return "H_" + name.upper()


def generate_handler_indices() -> dict[str, int]:
    discovered = _discover_handlers()
    existing = _load_registry()
    handlers = _update_registry(existing, discovered)
    _save_registry(handlers)

    missing = set(handlers[1:]) - discovered
    if missing:
        print(f"WARNING: registry has handlers not in code: {missing}", file=sys.stderr)

    index_map: dict[str, int] = {}
    lines = ["# Auto-generated from handler_registry.json — do not edit.", ""]
    for idx, func_name in enumerate(handlers):
        const = _func_to_const(func_name)
        index_map[const] = idx
        lines.append(f"{const} = {idx}")
    lines.append("")
    INDICES_PATH.write_text("\n".join(lines), encoding="utf-8")

    order_lines = [
        "# Auto-generated from handler_registry.json — do not edit.",
        "",
        "HANDLER_ORDER: tuple[str, ...] = (",
    ]
    for name in handlers:
        order_lines.append(f"    {name!r},")
    order_lines.append(")")
    order_lines.append("")
    ORDER_PATH.write_text("\n".join(order_lines), encoding="utf-8")

    return index_map


# ---------------------------------------------------------------------------
# Prefix -> handler mapping from BUFF_CONF
# ---------------------------------------------------------------------------

def _build_seed(h: dict[str, int]) -> tuple[dict[int, int], dict[int, int]]:
    prefix_seed: dict[int, int] = {
        PakOp.STAT_MOD: h["H_SELF_BUFF"],
        PakOp.IMMUNITY_LOCK: h["H_NOOP"],
        PakOp.LOCK_SWITCH: h["H_SELF_BUFF"],
        PakOp.LEECH: h["H_LEECH"],
        PakOp.BOSS_STUN: h["H_SELF_BUFF"],
        PakOp.STATUS_CONDITION: h["H_POISON"],
        PakOp.NEXT_PET: h["H_SELF_BUFF"],
        PakOp.DAMAGE_REDUCE: h["H_DAMAGE_REDUCTION"],
        PakOp.DOUBLE_ACTION: h["H_SELF_BUFF"],
        PakOp.STUN_HEAL: h["H_HIT_COUNT_DELTA"],
        PakOp.ON_HIT_REACTION: h["H_SELF_BUFF"],
        PakOp.PRIORITY: h["H_POWER_DYNAMIC"],
        PakOp.NUTRITION: h["H_HEAL_HP"],
        PakOp.POWER_MOD: h["H_POWER_DYNAMIC"],
        PakOp.EARTH_HEART: h["H_POWER_DYNAMIC"],
        PakOp.ELEMENT_VULN: h["H_SELF_BUFF"],
        PakOp.MOMENTUM: h["H_POWER_DYNAMIC"],
        PakOp.TEST_28: h["H_SELF_BUFF"],
        PakOp.FIRE_RAGE: h["H_POWER_DYNAMIC"],
        PakOp.COST_MOD: h["H_PASSIVE_ENERGY_REDUCE"],
        PakOp.ENTRY_AMBUSH: h["H_SELF_BUFF"],
        PakOp.OVERLOAD: h["H_POWER_DYNAMIC"],
        PakOp.ELEMENT_TRIGGER: h["H_SELF_BUFF"],
        PakOp.EFFICIENCY: h["H_PASSIVE_ENERGY_REDUCE"],
        PakOp.SURVIVAL: h["H_DAMAGE_REDUCTION"],
        PakOp.DUCK: h["H_SELF_BUFF"],
        PakOp.DETECTION: h["H_NOOP"],
        PakOp.HP_CONDITIONAL: h["H_SELF_BUFF"],
        PakOp.NON_SE_REDUCE: h["H_DAMAGE_REDUCTION"],
        PakOp.QUICK_START: h["H_SELF_BUFF"],
        PakOp.HIT_COUNT: h["H_HIT_COUNT_DELTA"],
        PakOp.ON_KILL: h["H_SELF_BUFF"],
        PakOp.FORCE_SWITCH: h["H_FORCE_SWITCH"],
        PakOp.TURN_END_TRANSFORM: h["H_SELF_BUFF"],
        PakOp.ENTRY_STATUS: h["H_SELF_BUFF"],
        PakOp.DREAM: h["H_SELF_BUFF"],
        PakOp.ENERGY_GAIN: h["H_HEAL_ENERGY"],
        PakOp.HEAL_MOD: h["H_HEAL_HP"],
        PakOp.DRAIN: h["H_LIFE_DRAIN"],
        PakOp.SKILL_COPY: h["H_SELF_BUFF"],
        PakOp.FREEZE_STATUS: h["H_FREEZE"],
        PakOp.COOLDOWN: h["H_NOOP"],
        PakOp.CHAR_SPECIFIC_A: h["H_SELF_BUFF"],
        PakOp.CONDITIONAL_TRIGGER: h["H_SELF_BUFF"],
        PakOp.COUNTER_REWARD: h["H_SELF_BUFF"],
        PakOp.POISON_FANG: h["H_POISON"],
        PakOp.DARK_HEAL: h["H_HEAL_HP"],
        PakOp.OTTER: h["H_SELF_BUFF"],
        PakOp.TEAM_ON_DEATH: h["H_SELF_BUFF"],
        PakOp.DOUBLE_TRIGGER: h["H_SELF_BUFF"],
        PakOp.SLEEPWALK: h["H_SELF_BUFF"],
        PakOp.SLOT_PRIORITY: h["H_SELF_BUFF"],
        PakOp.LANTERN: h["H_SELF_BUFF"],
        PakOp.CYCLOPS: h["H_SELF_BUFF"],
        PakOp.MIRROR_PRIORITY: h["H_SELF_BUFF"],
        PakOp.FEYNMAN: h["H_SELF_BUFF"],
        PakOp.CHAR_SPECIFIC_B: h["H_SELF_BUFF"],
        PakOp.ENERGY_HEAL: h["H_HEAL_ENERGY"],
        PakOp.CHARGE: h["H_SELF_BUFF"],
        PakOp.REFRACT: h["H_SELF_BUFF"],
        PakOp.DYNAMIC_HIT: h["H_HIT_COUNT_DELTA"],
        PakOp.FREEZE_LOCK: h["H_SELF_BUFF"],
        PakOp.ENTRY_FIRST_TURN: h["H_SELF_BUFF"],
        PakOp.MARK_METEOR: h["H_METEOR_MARK"],
        PakOp.ELEMENT_ENERGY: h["H_HEAL_ENERGY"],
        PakOp.EXTEND_ENTRY: h["H_SELF_BUFF"],
        PakOp.CUTE_SPEED: h["H_CUTE_GAIN"],
        PakOp.DIFF_SKILL_COST: h["H_SELF_BUFF"],
        PakOp.MAGIC_KILLER: h["H_SELF_BUFF"],
        PakOp.SKILL_CHECK: h["H_SELF_BUFF"],
        PakOp.POSITION_COST: h["H_SELF_BUFF"],
        PakOp.COND_POWER: h["H_POWER_DYNAMIC"],
        PakOp.FLAT_POWER: h["H_POWER_DYNAMIC"],
        PakOp.OVERFLOW_HEAL: h["H_HEAL_HP"],
        PakOp.MARK_NO_DECAY: h["H_SELF_BUFF"],
        PakOp.BURN_REVERSE: h["H_SELF_BUFF"],
        PakOp.COVER: h["H_SELF_BUFF"],
        PakOp.CAP_RAISE: h["H_SELF_BUFF"],
        PakOp.DRIVE: h["H_HIT_COUNT_DELTA"],
        PakOp.SLOT_MOD: h["H_SELF_BUFF"],
        PakOp.RETURN: h["H_SELF_BUFF"],
        PakOp.FIRST_USE_POWER: h["H_SELF_BUFF"],
        PakOp.SIDE_COST: h["H_SELF_BUFF"],
        PakOp.TEST: h["H_SELF_BUFF"],
        PakOp.ALERT: h["H_SELF_BUFF"],
        PakOp.BORROW: h["H_SELF_BUFF"],
        PakOp.FROG: h["H_SELF_BUFF"],
        PakOp.SEGMENT_HP: h["H_SELF_BUFF"],
        PakOp.HIT_BURN: h["H_BURN"],
        PakOp.CUTE_INFINITE: h["H_CUTE_GAIN"],
        PakOp.PURIFY: h["H_CLEANSE"],
        PakOp.COST_EFFICIENCY: h["H_PASSIVE_ENERGY_REDUCE"],
        PakOp.CANDY: h["H_CUTE_GAIN"],
        PakOp.MARK_CHANGE: h["H_SELF_BUFF"],
    }
    base_id_seed: dict[int, int] = {
        2007001: h["H_POISON"],
        2007002: h["H_BURN"],
        2005001: h["H_LEECH"],
        2032007: h["H_MOISTURE_MARK"],
        2021004: h["H_WIND_MARK"],
        2143001: h["H_MOISTURE_MARK"],
        2094001: h["H_METEOR_MARK"],
    }
    return prefix_seed, base_id_seed


def generate_prefix_map(handler_indices: dict[str, int], pak_data_dir: Path = PAK_DATA) -> dict:
    prefix_seed, base_id_seed = _build_seed(handler_indices)

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

    prefix_map: dict[int, int] = {}
    unmapped: list[int] = []
    for pfx in sorted(all_prefixes):
        if pfx in prefix_seed:
            prefix_map[pfx] = prefix_seed[pfx]
        else:
            prefix_map[pfx] = 0
            unmapped.append(pfx)

    return {
        "prefix_map": {str(k): v for k, v in sorted(prefix_map.items())},
        "base_id_map": {str(k): v for k, v in sorted(base_id_seed.items())},
        "stats": {
            "total_base_ids": len(all_base_ids),
            "total_prefixes": len(all_prefixes),
            "mapped_prefixes": len(all_prefixes) - len(unmapped),
            "unmapped_prefixes": unmapped,
        },
    }


def main() -> None:
    h = generate_handler_indices()
    print(f"handler_indices.py: {len(h)} constants -> {INDICES_PATH}")

    result = generate_prefix_map(h)
    PREFIX_MAP_PATH.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    stats = result["stats"]
    print(f"prefix_handler_map.json: {stats['total_prefixes']} prefixes "
          f"({stats['mapped_prefixes']} mapped, {len(stats['unmapped_prefixes'])} unmapped) -> {PREFIX_MAP_PATH}")
    if stats["unmapped_prefixes"]:
        print(f"  unmapped: {stats['unmapped_prefixes']}", file=sys.stderr)


if __name__ == "__main__":
    main()
