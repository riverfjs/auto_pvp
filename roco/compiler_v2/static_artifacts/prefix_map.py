from __future__ import annotations

import json

from roco.compiler_v2.handler_axes import resolve_handler_axes
from roco.compiler_v2.model import StaticBundle

from .common import PAK_BIN, PREFIX_MAP_PATH, _load_json_table, _maybe_int
from .marks import MARK_NOTE_BY_IDX


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
