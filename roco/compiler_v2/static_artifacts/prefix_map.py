from __future__ import annotations

import json

from roco.common.primitive_keys import status_note_key, struct_key
from roco.compiler_v2.model import StaticBundle
from roco.compiler_v2.primitive_axes import resolve_primitive_axes

from .common import PAK_BIN, PRIMITIVE_MAP_PATH, _load_json_table, _maybe_int
from .marks import mark_note_to_primitive


def write_primitive_map(bundle: StaticBundle) -> dict:
    buffbase_rows = _load_json_table(PAK_BIN / "BUFFBASE_CONF.json")
    buff_rows = _load_json_table(PAK_BIN / "BUFF_CONF.json")
    skill_rows = _load_json_table(PAK_BIN / "SKILL_CONF.json")

    axes = resolve_primitive_axes(bundle.lua_enums)
    order_seed = axes.buffbase_order
    prefix_seed = axes.prefix
    base_id_seed = axes.base_id

    base_id_via_order_map: dict[int, str] = {}
    for base_id, rec in buffbase_rows.items():
        if not isinstance(base_id, int):
            continue
        order = int(rec.get("buffbase_order") or 0)
        primitive = order_seed.get(order)
        if primitive is not None:
            base_id_via_order_map[base_id] = primitive

    all_prefixes: set[int] = set()
    all_base_ids: set[int] = set()
    for rec in buff_rows.values():
        for bid in rec.get("buff_base_ids") or []:
            if bid:
                all_base_ids.add(int(bid))
                all_prefixes.add(int(bid) // 1000)

    prefix_map = {
        pfx: primitive for pfx, primitive in sorted(prefix_seed.items())
        if pfx in all_prefixes
    }
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

    buff_id_map = _build_buff_id_primitive_map(
        bundle,
        buff_rows,
        buffbase_rows,
        skill_rows,
        axes.raw,
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
    PRIMITIVE_MAP_PATH.write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return {**result, "prefix_aliases": axes.prefix_aliases, "primitive_axes": axes}


def _build_buff_id_primitive_map(
    bundle: StaticBundle,
    buff_rows: dict[int | str, dict],
    buffbase_rows: dict[int | str, dict],
    skill_rows: dict[int | str, dict],
    raw_axes: dict[str, dict[int | str, tuple[str, str]]],
) -> dict[int, str]:
    """Derive exact BUFF_CONF.id primitives from pak structures.

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
    mark_name_to_primitive = mark_note_to_primitive(raw_axes)

    status_name_to_primitive = {
        desc_notes[note_id]: status_note_key(desc_notes[note_id])
        for note_id in (1001, 1002, 1008)
        if note_id in desc_notes
    }
    auto_switch_buff_ids = _derive_zero_energy_auto_switch_buff_ids(
        skill_rows,
        buff_rows,
        buffbase_rows,
    )

    out: dict[int, str] = {}
    for buff_id, rec in buff_rows.items():
        if not isinstance(buff_id, int):
            continue
        name = str(rec.get("name") or "").strip()
        primitive = mark_name_to_primitive.get(name)
        if primitive is not None:
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
            _put_exact_buff_primitive(out, buff_id, primitive, f"mark name={name!r}")
            continue

        labels = {
            str(rec.get(field) or "").strip()
            for field in ("name", "add_des")
            if str(rec.get(field) or "").strip()
        }
        if int(rec.get("type") or 0) == 2:
            for label in sorted(labels):
                primitive = status_name_to_primitive.get(label)
                if primitive is not None:
                    _put_exact_buff_primitive(out, buff_id, primitive, f"status label={label!r}")
                    break

        if buff_id in auto_switch_buff_ids:
            _put_exact_buff_primitive(
                out,
                buff_id,
                struct_key("zero_energy_auto_switch"),
                "SKILL_CONF order-52 zero-energy condition chain",
            )

        if _is_team_skill_hit_count_buff(rec, buffbase_rows):
            _put_exact_buff_primitive(
                out,
                buff_id,
                struct_key("team_skill_hit_count"),
                "BUFFBASE_CONF order-3 team skill count hit modifier",
            )

        if _is_flat_hit_count_delta_buff(rec, buffbase_rows):
            _put_exact_buff_primitive(
                out,
                buff_id,
                struct_key("flat_hit_count_delta"),
                "BUFFBASE_CONF order-45 flat hit-count delta",
            )

        if _is_heal_reversal_buff(rec, buffbase_rows):
            _put_exact_buff_primitive(
                out,
                buff_id,
                struct_key("heal_reversal"),
                "BUFFBASE_CONF order-146 heal reversal trigger",
            )

        if _is_cute_bench_cost_reduce_buff(rec, buff_rows, buffbase_rows):
            _put_exact_buff_primitive(
                out,
                buff_id,
                struct_key("cute_bench_cost_reduce"),
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

def _put_exact_buff_primitive(
    out: dict[int, str],
    buff_id: int,
    primitive: str,
    context: str,
) -> None:
    existing = out.get(buff_id)
    if existing is not None and existing != primitive:
        raise RuntimeError(
            f"BUFF_CONF[{buff_id}] exact primitive conflict: {existing} vs {primitive} ({context})"
        )
    out[buff_id] = primitive

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
