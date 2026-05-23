"""Replacement writer for all compiler-generated artifacts.

This module is the new implementation behind ``roco.compiler_v2.gen_prefix_map``.
It does not read handler-dispatch JSONL files.  Pak/Lua data comes through
``compiler_v2.sources``; handler coverage comes from engine-owned
``op_meta`` decorators collected via AST.
"""

from __future__ import annotations

import ast
import json
import sys
from enum import IntEnum
from pathlib import Path
from pprint import pformat
from typing import Any

from roco.common.enums import ELEMENT_NAMES, Stats, StatusType, WeatherType
from roco.compiler_v2.buff_immunity_decoders import (
    IMMUNITY_SPECS,
    load_buff_immunity_table,
)
from roco.compiler_v2.build import build_static_bundle
from roco.compiler_v2.emit import write_static_files
from roco.compiler_v2.handler_axes import OP_MODULES, resolve_handler_axes
from roco.compiler_v2.model import StaticBundle
from roco.compiler_v2.sources import DEFAULT_PAK_DATA_DIR


ROOT = Path(__file__).resolve().parents[2]
GEN_DIR = ROOT / "roco" / "generated"
PAK_DATA = DEFAULT_PAK_DATA_DIR
PAK_BIN = DEFAULT_PAK_DATA_DIR / "BinData"

INIT_PATH = GEN_DIR / "__init__.py"
REGISTRY_PATH = GEN_DIR / "handler_registry.json"
INDICES_PATH = GEN_DIR / "handler_indices.py"
ORDER_PATH = GEN_DIR / "handler_order.py"
TABLE_PATH = GEN_DIR / "handler_table.py"
PREFIX_MAP_PATH = GEN_DIR / "prefix_handler_map.json"
BATTLE_GLOBALS_PATH = GEN_DIR / "battle_globals.py"
PAK_OPS_PATH = GEN_DIR / "pak_ops.py"
SKILL_DAM_TYPES_PATH = GEN_DIR / "skill_dam_types.py"
TYPE_CHART_PATH = GEN_DIR / "type_chart.py"
WEATHER_DECODERS_PATH = GEN_DIR / "weather_decoders.py"
COUNTER_SKILL_TABLE_PATH = GEN_DIR / "counter_skill_table.py"
BUFFBASE_PARAMS_PATH = GEN_DIR / "buffbase_params.py"
BUFF_IMMUNITY_PATH = GEN_DIR / "buff_immunity_table.py"
MARK_GROUPS_PATH = GEN_DIR / "mark_groups.py"
NATURES_PATH = GEN_DIR / "natures.py"
CANONICAL_ADAPTERS_PATH = GEN_DIR / "canonical_adapters.py"
STATIC_DIR = GEN_DIR / "static"


class MarkIdx(IntEnum):
    MOISTURE = 0
    DRAGON = 1
    MOMENTUM = 2
    WIND = 3
    CHARGE = 4
    SOLAR = 5
    ATTACK = 6
    SLOW = 7
    SPIRIT = 8
    METEOR = 9
    POISON = 10
    THORN = 11
    SLUGGISH = 12


MARK_NOTE_BY_IDX: dict[MarkIdx, str] = {
    MarkIdx.MOISTURE: "湿润印记",
    MarkIdx.DRAGON: "龙噬印记",
    MarkIdx.MOMENTUM: "蓄势印记",
    MarkIdx.WIND: "风起印记",
    MarkIdx.CHARGE: "蓄电印记",
    MarkIdx.SOLAR: "光合印记",
    MarkIdx.ATTACK: "攻击印记",
    MarkIdx.SLOW: "减速印记",
    MarkIdx.SPIRIT: "降灵印记",
    MarkIdx.METEOR: "星陨印记",
    MarkIdx.POISON: "中毒印记",
    MarkIdx.THORN: "棘刺印记",
}

def write_all() -> dict[str, Any]:
    """Write every generated artifact and return build stats."""
    GEN_DIR.mkdir(parents=True, exist_ok=True)
    INIT_PATH.write_text('"""Auto-generated package for compiler_v2 artifacts."""\n', encoding="utf-8")
    bundle = build_static_bundle()
    static_paths = write_static_files(bundle, STATIC_DIR)

    handlers = write_handler_artifacts()
    prefix_result = write_prefix_handler_map(handlers, bundle)
    battle_global_count = write_battle_globals(bundle)
    skill_dam_type_count = write_skill_dam_types(bundle)
    mark_groups = write_mark_groups(handlers, prefix_result)
    pak_op_count = write_pak_ops(bundle, prefix_result["prefix_aliases"])
    type_chart_size = write_type_chart(bundle)
    weather_count = write_weather_decoders(bundle)
    counter_count = write_counter_skill_table(bundle)
    immunity_count = write_buff_immunity_table()
    buffbase_count = write_buffbase_params()
    nature_count = write_natures()
    canonical_adapter_counts = write_canonical_adapters()

    return {
        "source_hash": bundle.source_hash,
        "static_paths": static_paths,
        "handler_count": len(handlers),
        "prefix_stats": prefix_result["stats"],
        "battle_global_num_count": battle_global_count,
        "skill_dam_type_count": skill_dam_type_count,
        "mark_group_count": len(mark_groups),
        "pak_op_count": pak_op_count,
        "type_chart_size": type_chart_size,
        "weather_count": weather_count,
        "counter_count": counter_count,
        "immunity_count": immunity_count,
        "buffbase_count": buffbase_count,
        "nature_count": nature_count,
        "canonical_adapter_counts": canonical_adapter_counts,
    }


def _load_json_table(path: Path) -> dict[int | str, dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data.get("RocoDataRows", data)
    return {_coerce_key(k): v for k, v in rows.items()}


def _coerce_key(value: str) -> int | str:
    try:
        return int(value)
    except ValueError:
        return value


def _maybe_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _module_funcs() -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for mod_name in OP_MODULES:
        path = ROOT / (mod_name.replace(".", "/") + ".py")
        tree = ast.parse(path.read_text(encoding="utf-8"))
        result[mod_name] = [
            n.name for n in tree.body
            if isinstance(n, ast.FunctionDef) and n.name.startswith("op_")
        ]
    return result


def _discover_handlers() -> set[str]:
    return {name for names in _module_funcs().values() for name in names}


def _load_registry() -> list[str]:
    if REGISTRY_PATH.exists():
        return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))["handlers"]
    return ["_noop"]


def _save_registry(handlers: list[str]) -> None:
    payload = {
        "_meta": {
            "version": 2,
            "description": "Append-only handler registry generated by compiler_v2.",
        },
        "handlers": handlers,
    }
    REGISTRY_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _func_to_const(name: str) -> str:
    if name == "_noop":
        return "H_NOOP"
    if name.startswith("op_"):
        return "H_" + name[3:].upper()
    return "H_" + name.upper()


def write_handler_artifacts() -> dict[str, int]:
    discovered = _discover_handlers()
    handlers = _load_registry()
    known = set(handlers)
    handlers = handlers + sorted(discovered - known)
    missing = set(handlers[1:]) - discovered
    if missing:
        print(f"WARNING: registry has handlers not in code: {sorted(missing)}", file=sys.stderr)
    _save_registry(handlers)

    index_map: dict[str, int] = {}
    lines = ["# Auto-generated by compiler_v2 from handler_registry.json -- do not edit.", ""]
    for idx, func_name in enumerate(handlers):
        const = _func_to_const(func_name)
        index_map[const] = idx
        lines.append(f"{const} = {idx}")
    lines.append("")
    INDICES_PATH.write_text("\n".join(lines), encoding="utf-8")

    order_lines = [
        "# Auto-generated by compiler_v2 from handler_registry.json -- do not edit.",
        "",
        "HANDLER_ORDER: tuple[str, ...] = (",
    ]
    for name in handlers:
        order_lines.append(f"    {name!r},")
    order_lines.append(")")
    order_lines.append("")
    ORDER_PATH.write_text("\n".join(order_lines), encoding="utf-8")
    _write_handler_table(handlers)
    return index_map


def _write_handler_table(handlers: list[str]) -> None:
    func_to_module: dict[str, str] = {}
    by_module: dict[str, list[str]] = {m: [] for m in OP_MODULES}
    for mod_name, names in _module_funcs().items():
        for name in names:
            func_to_module[name] = mod_name
    for func_name in handlers:
        if func_name == "_noop":
            continue
        mod_name = func_to_module.get(func_name)
        if mod_name is None:
            raise RuntimeError(f"handler {func_name!r} not found in op modules")
        by_module[mod_name].append(func_name)

    lines = [
        "# Auto-generated by compiler_v2 -- do not edit.",
        "",
        "from roco.engine.kernel.ctx import StageCtx",
        "",
    ]
    for mod_name in OP_MODULES:
        names = by_module[mod_name]
        if not names:
            continue
        lines.append(f"from {mod_name} import (")
        for name in names:
            lines.append(f"    {name},")
        lines.append(")")
    lines.extend([
        "",
        "",
        "def _noop(_ctx: StageCtx, _row: tuple[int, ...]) -> None:",
        "    pass",
        "",
        "",
        "HANDLERS: tuple = (",
    ])
    for idx, name in enumerate(handlers):
        lines.append(f"    {name},  # {idx}")
    lines.extend([")", "", "HANDLER_COUNT = len(HANDLERS)", ""])
    TABLE_PATH.write_text("\n".join(lines), encoding="utf-8")


def _handler_idx(handler_indices: dict[str, int], handler_name: str) -> int:
    if handler_name == "H_NOOP":
        raise RuntimeError("H_NOOP is not a valid compiler output")
    if handler_name not in handler_indices:
        raise RuntimeError(f"unknown handler {handler_name!r}")
    return handler_indices[handler_name]


def write_prefix_handler_map(handler_indices: dict[str, int], bundle: StaticBundle) -> dict:
    buffbase_rows = _load_json_table(PAK_BIN / "BUFFBASE_CONF.json")
    buff_rows = _load_json_table(PAK_BIN / "BUFF_CONF.json")
    skill_rows = _load_json_table(PAK_BIN / "SKILL_CONF.json")

    axes = resolve_handler_axes(handler_indices, bundle.lua_enums)
    order_seed = axes.buffbase_order
    prefix_seed = axes.prefix
    base_id_seed = axes.base_id

    base_id_via_order_map: dict[int, int] = {}
    for base_id, rec in buffbase_rows.items():
        if not isinstance(base_id, int):
            continue
        order = int(rec.get("buffbase_order") or 0)
        h = order_seed.get(order)
        if h is not None:
            base_id_via_order_map[base_id] = h

    all_prefixes: set[int] = set()
    all_base_ids: set[int] = set()
    for rec in buff_rows.values():
        for bid in rec.get("buff_base_ids") or []:
            if bid:
                all_base_ids.add(int(bid))
                all_prefixes.add(int(bid) // 1000)

    prefix_map = {pfx: h for pfx, h in sorted(prefix_seed.items()) if pfx in all_prefixes}
    base_ids_by_prefix: dict[int, set[int]] = {}
    for bid in all_base_ids:
        base_ids_by_prefix.setdefault(bid // 1000, set()).add(bid)
    unmapped = []
    for pfx in sorted(all_prefixes):
        if pfx in prefix_map:
            continue
        if any(bid in base_id_via_order_map for bid in base_ids_by_prefix.get(pfx, ())):
            continue
        unmapped.append(pfx)

    buff_id_map = _build_buff_id_handler_map(
        handler_indices,
        bundle,
        buff_rows,
        buffbase_rows,
        skill_rows,
    )

    result = {
        "buff_id_map": {str(k): v for k, v in sorted(buff_id_map.items())},
        "prefix_map": {str(k): v for k, v in sorted(prefix_map.items())},
        "base_id_map": {str(k): v for k, v in sorted(base_id_seed.items())},
        "base_id_via_order_map": {str(k): v for k, v in sorted(base_id_via_order_map.items())},
        "stats": {
            "total_base_ids": len(all_base_ids),
            "total_prefixes": len(all_prefixes),
            "buff_ids_exact": len(buff_id_map),
            "mixed_prefix_count": len(prefix_map),
            "base_ids_via_order": len(base_id_via_order_map),
            "unmapped_prefixes": unmapped,
        },
    }
    PREFIX_MAP_PATH.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return {**result, "prefix_aliases": axes.prefix_aliases, "handler_axes": axes}


def _build_buff_id_handler_map(
    handler_indices: dict[str, int],
    bundle: StaticBundle,
    buff_rows: dict[int | str, dict],
    buffbase_rows: dict[int | str, dict],
    skill_rows: dict[int | str, dict],
) -> dict[int, int]:
    """Derive exact BUFF_CONF.id handlers from pak structures.

    Some mark buffs reuse generic BUFFBASE rows (for example poison or
    skill-cost rows).  A base_id-only dispatch would therefore compile the
    mark as the generic status/cost primitive.  The pak record itself carries
    the stable mark name, so this generated exact layer is keyed by
    ``BUFF_CONF.id`` and wins before base_id/order dispatch.

    The same exact layer handles status rows whose semantic is carried by
    ``BUFF_CONF.type/name/add_des``, plus structural outliers such as
    星地善良 where ``SKILL_CONF.skill_result`` chains an order-52 condition
    buff to an order-3 guard buff.  Those joins are compiler-owned static
    extraction; the engine does not carry pak names or ids.
    """

    bgs_area = bundle.lua_enums.get("BuffGroupSign", {}).get("BGS_AREA")
    desc_notes = _desc_notes_by_id()
    mark_name_to_handler: dict[str, int] = {}
    for mark_idx, note in MARK_NOTE_BY_IDX.items():
        const = f"H_{mark_idx.name}_MARK"
        handler = handler_indices.get(const)
        if handler is not None:
            mark_name_to_handler[note] = handler

    status_name_to_handler = {
        desc_notes[note_id]: handler_indices[const]
        for note_id, const in (
            (1001, "H_POISON"),
            (1002, "H_BURN"),
            (1008, "H_LEECH"),
        )
        if note_id in desc_notes and const in handler_indices
    }
    auto_switch_handler = handler_indices.get("H_AUTO_SWITCH_ON_ZERO_ENERGY")
    auto_switch_buff_ids = (
        _derive_zero_energy_auto_switch_buff_ids(skill_rows, buff_rows, buffbase_rows)
        if auto_switch_handler is not None
        else set()
    )
    team_skill_hit_handler = handler_indices.get("H_HIT_COUNT_BY_TEAM_SKILL_COUNT")
    hit_count_delta_handler = handler_indices.get("H_HIT_COUNT_DELTA")
    anti_heal_handler = handler_indices.get("H_ANTI_HEAL")
    cute_bench_cost_handler = handler_indices.get("H_CUTE_BENCH_COST_REDUCE")

    out: dict[int, int] = {}
    for buff_id, rec in buff_rows.items():
        if not isinstance(buff_id, int):
            continue
        name = str(rec.get("name") or "").strip()
        handler = mark_name_to_handler.get(name)
        if handler is not None:
            groups = {
                int(sign)
                for sign in rec.get("buff_groupsigns") or []
                if _maybe_int(sign) is not None
            }
            # Some pak rows omit BGS_AREA despite carrying the canonical mark
            # name.  The name is the semantic anchor; BGS_AREA only verifies the
            # common cover-group shape when present.
            if bgs_area is not None and groups and bgs_area not in groups:
                continue
            _put_exact_buff_handler(out, buff_id, handler, f"mark name={name!r}")
            continue

        labels = {
            str(rec.get(field) or "").strip()
            for field in ("name", "add_des")
            if str(rec.get(field) or "").strip()
        }
        if int(rec.get("type") or 0) == 2:
            for label in sorted(labels):
                handler = status_name_to_handler.get(label)
                if handler is not None:
                    _put_exact_buff_handler(out, buff_id, handler, f"status label={label!r}")
                    break

        if buff_id in auto_switch_buff_ids:
            _put_exact_buff_handler(
                out,
                buff_id,
                auto_switch_handler,
                "SKILL_CONF order-52 zero-energy condition chain",
            )

        if team_skill_hit_handler is not None and _is_team_skill_hit_count_buff(rec, buffbase_rows):
            _put_exact_buff_handler(
                out,
                buff_id,
                team_skill_hit_handler,
                "BUFFBASE_CONF order-3 team skill count hit modifier",
            )

        if hit_count_delta_handler is not None and _is_flat_hit_count_delta_buff(rec, buffbase_rows):
            _put_exact_buff_handler(
                out,
                buff_id,
                hit_count_delta_handler,
                "BUFFBASE_CONF order-45 flat hit-count delta",
            )

        if anti_heal_handler is not None and _is_heal_reversal_buff(rec, buffbase_rows):
            _put_exact_buff_handler(
                out,
                buff_id,
                anti_heal_handler,
                "BUFFBASE_CONF order-146 heal reversal trigger",
            )

        if (
            cute_bench_cost_handler is not None
            and _is_cute_bench_cost_reduce_buff(rec, buff_rows, buffbase_rows)
        ):
            _put_exact_buff_handler(
                out,
                buff_id,
                cute_bench_cost_handler,
                "BUFFBASE_CONF order-40 cute-stack trigger to all-skill cost reduction",
            )
    return out


def _is_team_skill_hit_count_buff(
    rec: dict,
    buffbase_rows: dict[int | str, dict],
) -> bool:
    base_ids = [int(v) for v in rec.get("buff_base_ids") or () if v]
    if len(base_ids) != 1:
        return False
    base = buffbase_rows.get(base_ids[0])
    if base is None or int(base.get("buffbase_order") or 0) != 3:
        return False
    slots = _base_param_slots(base)
    return len(slots) >= 2 and slots[0] == (3,) and bool(slots[1])


def _is_flat_hit_count_delta_buff(
    rec: dict,
    buffbase_rows: dict[int | str, dict],
) -> bool:
    base_ids = [int(v) for v in rec.get("buff_base_ids") or () if v]
    if len(base_ids) != 1:
        return False
    base = buffbase_rows.get(base_ids[0])
    if base is None or int(base.get("buffbase_order") or 0) != 45:
        return False
    slots = _base_param_slots(base)
    if len(slots) < 3:
        return False
    delta = _slot_scalar(slots, 0)
    skill_id = _slot_scalar(slots, 1)
    mode = _slot_scalar(slots, 2)
    return delta is not None and delta != 0 and skill_id == 0 and mode == 0


def _is_heal_reversal_buff(
    rec: dict,
    buffbase_rows: dict[int | str, dict],
) -> bool:
    base_ids = [int(v) for v in rec.get("buff_base_ids") or () if v]
    if len(base_ids) != 1:
        return False
    base = buffbase_rows.get(base_ids[0])
    if base is None or int(base.get("buffbase_order") or 0) != 146:
        return False
    slots = _base_param_slots(base)
    return (
        len(slots) >= 5
        and slots[0] == (24,)
        and slots[3] == (3, 20)
        and slots[4] == (-1,)
    )


def _is_cute_bench_cost_reduce_buff(
    rec: dict,
    buff_rows: dict[int | str, dict],
    buffbase_rows: dict[int | str, dict],
) -> bool:
    base_ids = [int(v) for v in rec.get("buff_base_ids") or () if v]
    if len(base_ids) != 1:
        return False
    base = buffbase_rows.get(base_ids[0])
    if base is None or int(base.get("buffbase_order") or 0) != 40:
        return False
    slots = _base_param_slots(base)
    if len(slots) < 3 or slots[1] != (1,) or len(slots[2]) != 1:
        return False
    if not slots[0] or not all(_is_cute_stack_buff(buff_id, buff_rows) for buff_id in slots[0]):
        return False
    return _all_skill_cost_reduce_amount(slots[2][0], buff_rows, buffbase_rows) == 1


def _is_cute_stack_buff(buff_id: int, buff_rows: dict[int | str, dict]) -> bool:
    rec = buff_rows.get(buff_id)
    if rec is None:
        return False
    base_ids = [int(v) for v in rec.get("buff_base_ids") or () if v]
    return len(base_ids) == 1 and base_ids[0] // 1000 == 2102


def _all_skill_cost_reduce_amount(
    buff_id: int,
    buff_rows: dict[int | str, dict],
    buffbase_rows: dict[int | str, dict],
) -> int:
    rec = buff_rows.get(buff_id)
    if rec is None:
        return 0
    base_ids = [int(v) for v in rec.get("buff_base_ids") or () if v]
    if len(base_ids) != 1:
        return 0
    base = buffbase_rows.get(base_ids[0])
    if base is None or int(base.get("buffbase_order") or 0) != 32:
        return 0
    slots = _base_param_slots(base)
    if len(slots) < 4 or slots[0] != (0,) or len(slots[3]) != 1:
        return 0
    delta = slots[3][0]
    return abs(delta) if delta < 0 else 0


def _put_exact_buff_handler(
    out: dict[int, int],
    buff_id: int,
    handler: int,
    context: str,
) -> None:
    existing = out.get(buff_id)
    if existing is not None and existing != handler:
        raise RuntimeError(
            f"BUFF_CONF[{buff_id}] exact handler conflict: {existing} vs {handler} ({context})"
        )
    out[buff_id] = handler


def _desc_notes_by_id() -> dict[int, str]:
    rows = _load_json_table(PAK_BIN / "DESC_NOTE_CONF.json")
    return {
        note_id: str(rec.get("note") or "").strip()
        for note_id, rec in rows.items()
        if isinstance(note_id, int) and str(rec.get("note") or "").strip()
    }


def _base_param_slots(rec: dict) -> tuple[tuple[int, ...], ...]:
    slots: list[tuple[int, ...]] = []
    for raw in rec.get("buffbase_param") or rec.get("params") or []:
        if isinstance(raw, dict):
            inner = raw.get("params") or []
        elif isinstance(raw, list):
            inner = raw
        else:
            inner = [raw]
        values: list[int] = []
        for value in inner:
            maybe = _maybe_int(value)
            if maybe is not None:
                values.append(maybe)
        slots.append(tuple(values))
    return tuple(slots)


def _slot_scalar(slots: tuple[tuple[int, ...], ...], index: int) -> int | None:
    if index >= len(slots) or len(slots[index]) != 1:
        return None
    return slots[index][0]


def _iter_buff_base_slots(
    buff_id: int,
    buff_rows: dict[int | str, dict],
    buffbase_rows: dict[int | str, dict],
) -> list[tuple[int, int, tuple[tuple[int, ...], ...]]]:
    out: list[tuple[int, int, tuple[tuple[int, ...], ...]]] = []
    rec = buff_rows.get(buff_id) or {}
    for raw_base_id in rec.get("buff_base_ids") or []:
        base_id = _maybe_int(raw_base_id)
        if base_id is None:
            continue
        base = buffbase_rows.get(base_id) or {}
        order = _maybe_int(base.get("buffbase_order")) or 0
        out.append((base_id, order, _base_param_slots(base)))
    return out


def _derive_zero_energy_auto_switch_buff_ids(
    skill_rows: dict[int | str, dict],
    buff_rows: dict[int | str, dict],
    buffbase_rows: dict[int | str, dict],
) -> set[int]:
    """Find order-3 guard buffs paired with an order-52 zero-energy condition."""

    out: set[int] = set()
    for skill in skill_rows.values():
        direct_buff_ids: list[int] = []
        for entry in skill.get("skill_result") or []:
            if not isinstance(entry, dict):
                continue
            effect_id = _maybe_int(entry.get("effect_id"))
            if effect_id is not None and effect_id in buff_rows:
                direct_buff_ids.append(effect_id)
        if not direct_buff_ids:
            continue
        direct_buff_ids = list(dict.fromkeys(direct_buff_ids))

        condition_targets: set[int] = set()
        for buff_id in direct_buff_ids:
            for _base_id, order, slots in _iter_buff_base_slots(buff_id, buff_rows, buffbase_rows):
                target = _slot_scalar(slots, 2)
                if order == 52 and _slot_scalar(slots, 0) == 0 and target in buff_rows:
                    condition_targets.add(target)
        if not condition_targets:
            continue

        for buff_id in direct_buff_ids:
            for _base_id, order, slots in _iter_buff_base_slots(buff_id, buff_rows, buffbase_rows):
                if order != 3:
                    continue
                refs = {value for slot in slots for value in slot}
                if refs & condition_targets:
                    out.add(buff_id)
    return out


def _assign(name: str, value: Any) -> str:
    return f"{name} = {pformat(value, width=100, sort_dicts=True)}\n"


def write_battle_globals(bundle: StaticBundle) -> int:
    lines = [
        "# Auto-generated by compiler_v2 from the full BATTLE_GLOBAL_CONFIG.json -- do not edit.",
        "",
        "from __future__ import annotations",
        "",
    ]
    lines.append(_assign("BATTLE_GLOBAL_NUMS", bundle.battle_global_nums).rstrip())
    lines.append(_assign("BATTLE_GLOBAL_LISTS", bundle.battle_global_lists).rstrip())
    lines.append(_assign("BATTLE_GLOBAL_STRINGS", bundle.battle_global_strings).rstrip())
    lines.append("")
    BATTLE_GLOBALS_PATH.write_text("\n".join(lines), encoding="utf-8")
    return len(bundle.battle_global_nums)


def write_skill_dam_types(bundle: StaticBundle) -> int:
    lines = [
        "# Auto-generated by compiler_v2 from Enum.SkillDamType + TYPE_DICTIONARY.json -- do not edit.",
        "",
        "from __future__ import annotations",
        "",
    ]
    lines.append(_assign("SKILL_DAM_TYPE_NAMES", bundle.skill_dam_type_names).rstrip())
    lines.append(_assign("SKILL_DAM_TYPE_TO_ELEMENT", bundle.skill_dam_type_to_element).rstrip())
    lines.append(_assign("SKILL_DAM_TYPE_TO_ELEMENT_NAME", bundle.skill_dam_type_to_element_name).rstrip())
    lines.append(_assign("SKILL_DAM_TYPE_UNMAPPED", bundle.skill_dam_type_unmapped).rstrip())
    lines.append("")
    SKILL_DAM_TYPES_PATH.write_text("\n".join(lines), encoding="utf-8")
    return len(bundle.skill_dam_type_to_element)


def _runtime_stat_keys() -> tuple[str, ...]:
    return tuple(member.name.lower() for member in sorted(Stats, key=lambda s: s.value))


def build_nature_tables(pak_bin: Path = PAK_BIN) -> dict[str, Any]:
    nature_rows = _load_json_table(pak_bin / "NATURE_CONF.json")
    attribute_rows = _load_json_table(pak_bin / "ATTRIBUTE_CONF.json")

    stat_keys = _runtime_stat_keys()
    nature_attribute_ids = sorted({
        int(rec[field])
        for rec in nature_rows.values()
        for field in ("positive_effect", "negative_effect")
        if _maybe_int(rec.get(field)) is not None
    })
    battle_attrs = sorted(
        (attr_id, rec)
        for attr_id in nature_attribute_ids
        if (rec := attribute_rows.get(attr_id)) is not None
    )
    if len(battle_attrs) != len(stat_keys):
        raise RuntimeError(
            f"NATURE_CONF attribute count {len(battle_attrs)} != Stats count {len(stat_keys)}"
        )
    stat_key_by_attribute_id = {
        attr_id: stat_key
        for (attr_id, _rec), stat_key in zip(battle_attrs, stat_keys, strict=True)
    }
    iv_stat_map = {
        str(rec.get("attribute_name") or rec.get("editor_name")).strip(): stat_key_by_attribute_id[attr_id]
        for attr_id, rec in battle_attrs
        if str(rec.get("attribute_name") or rec.get("editor_name") or "").strip()
    }

    nature_mod_by_id: dict[int, tuple[str, str]] = {}
    nature_effects_by_id: dict[int, tuple[str, int, str, int]] = {}
    player_nature_ids: list[int] = []
    nature_name_to_id: dict[str, int] = {}
    nature_mod: dict[str, tuple[str, str]] = {}
    nature_effects_by_name: dict[str, tuple[str, int, str, int]] = {}

    for nature_id, rec in sorted(nature_rows.items()):
        if not isinstance(nature_id, int):
            continue
        name = str(rec.get("name") or "").strip()
        if not name:
            continue
        positive_attr = int(rec.get("positive_effect") or 0)
        negative_attr = int(rec.get("negative_effect") or 0)
        try:
            positive_key = stat_key_by_attribute_id[positive_attr]
            negative_key = stat_key_by_attribute_id[negative_attr]
        except KeyError as exc:
            raise RuntimeError(f"NATURE_CONF {nature_id} references unknown attribute {exc.args[0]}") from exc
        positive_bps = int(rec.get("positive_effect_proportion") or 0)
        negative_bps = int(rec.get("negative_effect_proportion") or 0)
        pair = (positive_key, negative_key)
        effect = (positive_key, positive_bps, negative_key, negative_bps)
        nature_mod_by_id[nature_id] = pair
        nature_effects_by_id[nature_id] = effect
        if rec.get("is_player_pet_nature") is not True:
            continue
        if name in nature_name_to_id:
            raise RuntimeError(
                f"duplicate player nature name {name!r}: "
                f"{nature_name_to_id[name]} and {nature_id}"
            )
        player_nature_ids.append(nature_id)
        nature_name_to_id[name] = nature_id
        nature_mod[name] = pair
        nature_effects_by_name[name] = effect

    return {
        "attribute_stat_keys": dict(sorted(stat_key_by_attribute_id.items())),
        "iv_stat_map": dict(sorted(iv_stat_map.items())),
        "nature_mod_by_id": dict(sorted(nature_mod_by_id.items())),
        "nature_effects_by_id": dict(sorted(nature_effects_by_id.items())),
        "player_nature_ids": tuple(sorted(player_nature_ids)),
        "nature_name_to_id": dict(sorted(nature_name_to_id.items(), key=lambda item: item[1])),
        "nature_mod": dict(sorted(nature_mod.items(), key=lambda item: nature_name_to_id[item[0]])),
        "nature_effects_by_name": dict(
            sorted(nature_effects_by_name.items(), key=lambda item: nature_name_to_id[item[0]])
        ),
    }


def write_natures() -> int:
    tables = build_nature_tables()
    lines = [
        "# Auto-generated by compiler_v2 from NATURE_CONF.json + ATTRIBUTE_CONF.json -- do not edit.",
        "",
        "from __future__ import annotations",
        "",
    ]
    lines.append(_assign("ATTRIBUTE_STAT_KEYS", tables["attribute_stat_keys"]).rstrip())
    lines.append(_assign("IV_STAT_MAP", tables["iv_stat_map"]).rstrip())
    lines.append(_assign("NATURE_MOD_BY_ID", tables["nature_mod_by_id"]).rstrip())
    lines.append(_assign("NATURE_EFFECTS_BY_ID", tables["nature_effects_by_id"]).rstrip())
    lines.append(_assign("PLAYER_NATURE_IDS", tables["player_nature_ids"]).rstrip())
    lines.append(_assign("NATURE_NAME_TO_ID", tables["nature_name_to_id"]).rstrip())
    lines.append(_assign("NATURE_MOD", tables["nature_mod"]).rstrip())
    lines.append(_assign("NATURE_EFFECTS_BY_NAME", tables["nature_effects_by_name"]).rstrip())
    lines.append("")
    NATURES_PATH.write_text("\n".join(lines), encoding="utf-8")
    return len(tables["nature_mod"])


def _canonical_skill_category_from_pak(row: dict[str, Any]) -> str:
    skill_type = _maybe_int(row.get("Skill_Type")) or 0
    damage_type = _maybe_int(row.get("damage_type")) or 0
    if skill_type == 3:
        return "防御"
    if skill_type == 2:
        return "状态"
    if damage_type == 2:
        return "物攻"
    if damage_type in {3, 4}:
        return "魔攻"
    return "状态"


def build_canonical_adapters(pak_data: Path = PAK_DATA, pak_bin: Path = PAK_BIN) -> dict[str, Any]:
    skill_rows = _load_json_table(pak_bin / "SKILL_CONF.json")
    desc_note_rows = _load_json_table(pak_bin / "DESC_NOTE_CONF.json")
    moves = json.loads((pak_data / "moves.json").read_text(encoding="utf-8"))
    category_map: dict[str, str] = {}
    conflicts: dict[str, set[str]] = {}
    for move in moves:
        if not isinstance(move, dict):
            continue
        english = str(move.get("move_category") or "").strip()
        skill_id = _maybe_int(move.get("id"))
        if not english or skill_id is None:
            continue
        row = skill_rows.get(skill_id)
        if row is None:
            continue
        canonical = _canonical_skill_category_from_pak(row)
        existing = category_map.get(english)
        if existing is not None and existing != canonical:
            conflicts.setdefault(english, {existing}).add(canonical)
            continue
        category_map[english] = canonical
    if conflicts:
        details = {key: sorted(values) for key, values in sorted(conflicts.items())}
        raise RuntimeError(f"conflicting move category adapters from moves.json/SKILL_CONF: {details}")

    desc_id_by_note: dict[str, int] = {}
    for desc_id, rec in desc_note_rows.items():
        if not isinstance(desc_id, int):
            continue
        note = str(rec.get("note") or "").strip()
        if note:
            desc_id_by_note[note] = desc_id

    mark_defs: list[tuple[int, str, int, str]] = []
    for idx in sorted(MARK_NOTE_BY_IDX, key=lambda item: item.value):
        note = MARK_NOTE_BY_IDX[idx]
        desc_id = desc_id_by_note.get(note)
        if desc_id is None:
            raise RuntimeError(f"DESC_NOTE_CONF missing canonical mark note {note!r}")
        polarity = "positive" if idx.value <= MarkIdx.ATTACK.value or idx == MarkIdx.SLUGGISH else "negative"
        mark_defs.append((desc_id, idx.name.lower(), int(idx.value), polarity))

    return {
        "move_category_to_cn": dict(sorted(category_map.items())),
        "canonical_mark_defs": tuple(mark_defs),
    }


def write_canonical_adapters() -> dict[str, int]:
    tables = build_canonical_adapters()
    lines = [
        "# Auto-generated by compiler_v2 from moves.json + SKILL_CONF.json + DESC_NOTE_CONF.json -- do not edit.",
        "",
        "from __future__ import annotations",
        "",
    ]
    lines.append(_assign("MOVE_CATEGORY_TO_CN", tables["move_category_to_cn"]).rstrip())
    lines.append(_assign("CANONICAL_MARK_DEFS", tables["canonical_mark_defs"]).rstrip())
    lines.append("")
    CANONICAL_ADAPTERS_PATH.write_text("\n".join(lines), encoding="utf-8")
    return {
        "move_category_count": len(tables["move_category_to_cn"]),
        "mark_def_count": len(tables["canonical_mark_defs"]),
    }


def write_pak_ops(bundle: StaticBundle, prefix_aliases: dict[int, str]) -> int:
    buff_rows = _load_json_table(PAK_BIN / "BUFF_CONF.json")
    prefixes: set[int] = set()
    for rec in buff_rows.values():
        for bid in rec.get("buff_base_ids") or []:
            if bid:
                prefixes.add(int(bid) // 1000)
    lines = [
        "# Auto-generated by compiler_v2 from BUFF_CONF + engine handler metadata -- do not edit.",
        "",
        "EFF_BUFF_APPLY = 10001",
        "EFF_DAMAGE = 10002",
        "EFF_STATE_CHANGE = 10003",
        "",
        "PAK_PREFIX_NAMES: dict[int, str] = {",
    ]
    for pfx in sorted(prefixes):
        name = prefix_aliases.get(pfx)
        if name is None:
            order = pfx - 2000
            name = bundle.buffbase_order_names.get(order, f"PREFIX_{pfx}")
        lines.append(f"    {pfx}: {name!r},")
    lines.append("}")
    lines.append("")
    PAK_OPS_PATH.write_text("\n".join(lines), encoding="utf-8")
    return len(prefixes)


def write_type_chart(bundle: StaticBundle) -> int:
    rows = _load_json_table(PAK_BIN / "TYPE_DICTIONARY.json")
    by_short = {rec.get("short_name"): rec for rec in rows.values() if rec.get("short_name")}
    pak_ids: list[int] = []
    for name in ELEMENT_NAMES:
        rec = by_short.get(name)
        if rec is None:
            raise RuntimeError(f"TYPE_DICTIONARY missing short_name={name!r}")
        pak_ids.append(int(rec["id"]))
    neutral = bundle.battle_global_nums["restraint_percent"]
    weak = bundle.battle_global_nums["double_restraint_percent"]
    resist = bundle.battle_global_nums["restrained_percent"]
    n = len(ELEMENT_NAMES)
    chart = [[neutral] * n for _ in range(n)]
    for attacker_idx, attacker_name in enumerate(ELEMENT_NAMES):
        rec = by_short[attacker_name]
        for defender_idx, defender_pak_id in enumerate(pak_ids):
            sign = rec.get(f"type_restraint{defender_pak_id}", 0)
            if sign == 1:
                chart[attacker_idx][defender_idx] = weak
            elif sign == -1:
                chart[attacker_idx][defender_idx] = resist
    lines = [
        "# Auto-generated by compiler_v2 from TYPE_DICTIONARY.json -- do not edit.",
        "",
        f"# Element order matches roco.common.enums.ELEMENT_NAMES (length {n}).",
        "TYPE_CHART_BPS: tuple[tuple[int, ...], ...] = (",
    ]
    for idx, name in enumerate(ELEMENT_NAMES):
        lines.append(f"    ({', '.join(str(v) for v in chart[idx])}),  # {idx:2d} {name}")
    lines.append(")")
    lines.append("")
    TYPE_CHART_PATH.write_text("\n".join(lines), encoding="utf-8")
    return n


def write_weather_decoders(bundle: StaticBundle | None = None) -> int:
    if bundle is None:
        bundle = build_static_bundle()
    rows = _load_json_table(PAK_BIN / "EFFECT_CONF.json")
    weather_symbols_by_value = {
        int(value): str(symbol)
        for symbol, value in bundle.lua_enums["WeatherType"].items()
    }
    decoded: list[tuple[int, str, int, int]] = []
    for eid, rec in rows.items():
        if not isinstance(eid, int):
            continue
        if int(rec.get("effect_order") or 0) != 28 or int(rec.get("type") or 0) != 3:
            continue
        params = rec.get("effect_param") or []
        if not params or not isinstance(params[0], dict):
            continue
        inner = params[0].get("params") or []
        if not inner:
            continue
        pak_symbol = weather_symbols_by_value.get(int(inner[0]))
        if pak_symbol is None:
            continue
        kernel_name = _kernel_weather_name(pak_symbol)
        if kernel_name is None:
            continue
        decoded.append((
            eid,
            kernel_name,
            int(getattr(WeatherType, kernel_name).value),
            _default_weather_turns(kernel_name),
        ))
    lines = [
        "# Auto-generated by compiler_v2 from EFFECT_CONF.json -- do not edit.",
        "",
        "from roco.generated.handler_indices import H_WEATHER",
        "",
        "WEATHER_EFFECT_DECODERS: dict[int, tuple[int, int, int, int, int, int]] = {",
    ]
    for eid, name, value, turns in sorted(decoded):
        lines.append(f"    {eid}: (H_WEATHER, {value}, {turns}, 0, 0, 0),  # pak {name}")
    lines.append("}")
    lines.append("")
    WEATHER_DECODERS_PATH.write_text("\n".join(lines), encoding="utf-8")
    return len(decoded)


def _kernel_weather_name(pak_symbol: str) -> str | None:
    if pak_symbol in ("WT_NONE", "WT_SUNNY"):
        return "NONE"
    if pak_symbol.endswith("RAIN"):
        return "RAIN"
    if pak_symbol in ("WT_SNOW", "WT_SNOWSTORM"):
        return "SNOW"
    if pak_symbol == "WT_SANDSTORM":
        return "SANDSTORM"
    return None


def _default_weather_turns(kernel_name: str) -> int:
    return 0 if kernel_name == "NONE" else 8


def write_counter_skill_table(bundle: StaticBundle) -> int:
    effect_rows = _load_json_table(PAK_BIN / "EFFECT_CONF.json")
    skill_rows = _load_json_table(PAK_BIN / "SKILL_CONF.json")
    counter_skill_ids: set[int] = set()
    for rec in effect_rows.values():
        if int(rec.get("effect_order") or 0) != 31:
            continue
        params = rec.get("effect_param") or []
        if not params or not isinstance(params[0], dict):
            continue
        inner = params[0].get("params") or []
        if not inner:
            continue
        skill_id = int(inner[0])
        if 7000000 <= skill_id < 8000000:
            counter_skill_ids.add(skill_id)
    table: list[tuple[int, int, int, int, int, int, str]] = []
    for skill_id in sorted(counter_skill_ids):
        row = skill_rows.get(skill_id)
        if row is None:
            continue
        dam_para = row.get("dam_para") or [0]
        power = int(dam_para[0] if isinstance(dam_para, list) and dam_para else 0)
        element = bundle.skill_dam_type_to_element.get(int(row.get("skill_dam_type") or 0), 0)
        pak_damage_type = int(row.get("damage_type") or 0)
        pak_skill_type = int(row.get("Skill_Type") or 0)
        if pak_damage_type == 2:
            category = 1
        elif pak_damage_type == 3:
            category = 2
        elif pak_skill_type == 3:
            category = 3
        elif pak_skill_type == 2:
            category = 4
        else:
            category = 0
        table.append((
            skill_id,
            power,
            element,
            category,
            pak_damage_type,
            int(row.get("skill_priority") or 0),
            str(row.get("name") or ""),
        ))
    lines = [
        "# Auto-generated by compiler_v2 from SKILL_CONF + EFFECT_CONF -- do not edit.",
        "",
        "COUNTER_SKILL_TABLE: dict[int, tuple[int, int, int, int, int]] = {",
    ]
    for skill_id, power, element, category, dam_type, priority, name in table:
        lines.append(f"    {skill_id}: ({power}, {element}, {category}, {dam_type}, {priority}),  # {name}")
    lines.append("}")
    lines.append("")
    COUNTER_SKILL_TABLE_PATH.write_text("\n".join(lines), encoding="utf-8")
    return len(table)


def _normalize_slot(slot: Any) -> tuple[int, ...] | int:
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
    raw = rec.get("buffbase_param") or rec.get("params") or []
    return tuple(_normalize_slot(slot) for slot in raw)


def build_buffbase_tables(pak_bin: Path = PAK_BIN) -> dict[str, dict[int, Any]]:
    rows = _load_json_table(pak_bin / "BUFFBASE_CONF.json")
    params: dict[int, tuple] = {}
    order: dict[int, int] = {}
    trigger: dict[int, int] = {}
    for base_id, rec in rows.items():
        if not isinstance(base_id, int):
            continue
        params[base_id] = _record_param_tuple(rec)
        order[base_id] = int(rec.get("buffbase_order") or 0)
        trigger[base_id] = int(rec.get("trigger_type") or 0)
    return {"params": params, "order": order, "trigger": trigger}


def write_buffbase_params() -> int:
    tables = build_buffbase_tables()
    lines = [
        "# Auto-generated by compiler_v2 from BUFFBASE_CONF.json -- do not edit.",
        "",
        "from typing import Any",
        "",
        "BUFFBASE_PARAMS: dict[int, tuple] = {",
    ]
    for base_id in sorted(tables["params"]):
        lines.append(f"    {base_id}: {tables['params'][base_id]!r},")
    lines.append("}")
    lines.append("")
    lines.append("BUFFBASE_ORDER: dict[int, int] = {")
    for base_id in sorted(tables["order"]):
        lines.append(f"    {base_id}: {tables['order'][base_id]},")
    lines.append("}")
    lines.append("")
    lines.append("BUFFBASE_TRIGGER_TYPE: dict[int, int] = {")
    for base_id in sorted(tables["trigger"]):
        lines.append(f"    {base_id}: {tables['trigger'][base_id]},")
    lines.append("}")
    lines.append("")
    BUFFBASE_PARAMS_PATH.write_text("\n".join(lines), encoding="utf-8")
    return len(tables["params"])


def write_buff_immunity_table() -> int:
    table = load_buff_immunity_table()
    status_members = {member.name: int(member.value) for member in StatusType}
    status_pairs = []
    for spec in IMMUNITY_SPECS:
        status_name = spec.tag.upper()
        if status_name in status_members:
            status_pairs.append((status_members[status_name], status_name, spec.const_name))
    status_pairs.sort()
    lines = [
        '"""Auto-generated by compiler_v2 from BUFF_CONF.desc immunity phrases -- do not edit."""',
        "",
        "from __future__ import annotations",
        "",
    ]
    max_name_len = max(len(s.const_name) for s in IMMUNITY_SPECS)
    for spec in IMMUNITY_SPECS:
        pad = " " * (max_name_len - len(spec.const_name))
        lines.append(f"{spec.const_name}{pad} = 0x{spec.bit:02X}")
    lines.append("")
    lines.append("BUFF_IMMUNITY_TABLE: dict[int, int] = {")
    for buff_id in sorted(table):
        flags = table[buff_id]
        used = [s for s in IMMUNITY_SPECS if flags & s.bit]
        expr = " | ".join(s.const_name for s in used) if used else "0"
        lines.append(f"    {buff_id}: {expr},")
    lines.append("}")
    lines.append("")
    lines.append("STATUS_IMMUNITY_FLAGS_BY_STATUS_TYPE: dict[int, int] = {")
    for status_value, status_name, const_name in status_pairs:
        lines.append(f"    {status_value}: {const_name},  # StatusType.{status_name}")
    lines.append("}")
    lines.append("")
    BUFF_IMMUNITY_PATH.write_text("\n".join(lines), encoding="utf-8")
    return len(table)


def write_mark_groups(handler_indices: dict[str, int], prefix_result: dict) -> tuple[tuple[str, ...], ...]:
    valid_mark_names = {idx.name for idx in MarkIdx}
    handler_to_mark = {
        handler_indices[key]: key.removeprefix("H_").removesuffix("_MARK")
        for key in handler_indices
        if key.endswith("_MARK")
        and key.removeprefix("H_").removesuffix("_MARK") in valid_mark_names
    }
    if not handler_to_mark:
        MARK_GROUPS_PATH.write_text(
            "from roco.common.packing import MarkIdx  # noqa: F401\n"
            "MARK_COVER_GROUPS: tuple = ()\n",
            encoding="utf-8",
        )
        return ()
    mark_handlers = set(handler_to_mark)
    buff_id_map = {int(k): v for k, v in prefix_result.get("buff_id_map", {}).items()}
    base_id_map = {int(k): v for k, v in prefix_result["base_id_map"].items()}
    prefix_map = {int(k): v for k, v in prefix_result["prefix_map"].items()}
    groups: dict[int, set[int]] = {}
    for buff_id, rec in _load_json_table(PAK_BIN / "BUFF_CONF.json").items():
        handler = 0
        if isinstance(buff_id, int):
            h = buff_id_map.get(buff_id, 0)
            if h in mark_handlers:
                handler = h
        for bid in rec.get("buff_base_ids") or []:
            if handler:
                break
            bid = int(bid)
            if bid in base_id_map and base_id_map[bid] in mark_handlers:
                handler = base_id_map[bid]
                break
            pfx = bid // 1000
            if pfx in prefix_map and prefix_map[pfx] in mark_handlers:
                handler = prefix_map[pfx]
                break
        if not handler:
            continue
        for sign in rec.get("buff_groupsigns") or []:
            if sign:
                groups.setdefault(int(sign), set()).add(handler)
    cover_groups: list[tuple[str, ...]] = []
    for handlers in groups.values():
        if len(handlers) < 2:
            continue
        names = tuple(sorted(handler_to_mark[h] for h in handlers if h in handler_to_mark))
        if len(names) >= 2:
            cover_groups.append(names)
    lines = [
        "# Auto-generated by compiler_v2 from BUFF_CONF.buff_groupsigns -- do not edit.",
        "",
        "from roco.common.packing import MarkIdx",
        "",
        "MARK_COVER_GROUPS: tuple[tuple[MarkIdx, ...], ...] = (",
    ]
    for names in cover_groups:
        lines.append(f"    ({', '.join(f'MarkIdx.{name}' for name in names)}),")
    lines.append(")")
    lines.append("")
    MARK_GROUPS_PATH.write_text("\n".join(lines), encoding="utf-8")
    return tuple(cover_groups)
