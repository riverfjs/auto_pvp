"""Link compiler primitive rows to engine runtime op names."""

from __future__ import annotations

from typing import Iterable

from roco.common.enums import Element
from roco.common.primitive_keys import (
    BATTLE_EVENT_PREFIX,
    ENGINE_HOOK_PREFIX,
    buff_type_key,
    strip_prefix,
)
from roco.engine.artifacts.linked_op import LinkedOp
from roco.engine.artifacts.pak_ref_linker import link_pak_ref
from roco.engine.artifacts.primitive_bindings import op_name_from_primitive
from roco.engine.kernel.op_rows import TIMING_HOOK_BEFORE_MOVE, TIMING_PAK_SDT
from roco.generated.battle_events import BATTLE_EVENT_VALUES
from roco.generated.buffbase_params import BUFFBASE_ORDER, BUFFBASE_PARAMS
from roco.generated.effect_params import EFFECT_ORDER, EFFECT_PARAMS, EFFECT_TYPE
from roco.generated.skill_dam_types import SKILL_DAM_TYPE_TO_ELEMENT
from roco.generated.static.lua_enums import BUFF_TYPE, EFFECT_TYPE as EFFECT_TYPE_ENUM


PrimitiveRow = tuple[str, str, int, int, int, int, int, int]

ENGINE_HOOK_TIMINGS = {
    "before_move": TIMING_HOOK_BEFORE_MOVE,
}

P_BFT_O_T = buff_type_key("BFT_O_T")
BFT_O_T = int(BUFF_TYPE["BFT_O_T"])
ET_CHANGE_ENERGY = int(EFFECT_TYPE_ENUM["ET_CHANGE_ENERGY"])


def primitive_to_op_name(primitive: str) -> str:
    return op_name_from_primitive(primitive)


def link_primitive_row(row: Iterable[object], *, source_name: str) -> LinkedOp:
    """Convert one compiler primitive row to one engine linked op."""

    rows = link_primitive_rows(row, source_name=source_name)
    if len(rows) != 1:
        raise RuntimeError(
            f"{source_name!r} produced primitive row that linked to {len(rows)} runtime rows"
        )
    return rows[0]


def link_primitive_rows(row: Iterable[object], *, source_name: str) -> tuple[LinkedOp, ...]:
    """Convert a compiler primitive row to one or more engine linked ops."""

    values = tuple(row)
    if len(values) != 8:
        raise RuntimeError(f"{source_name!r} produced malformed primitive row: {values!r}")
    primitive_raw, timing_raw, target, rate, p0, p1, p2, p3 = values
    primitive = str(primitive_raw)
    if not primitive:
        raise RuntimeError(f"{source_name!r} produced an empty effect primitive")
    timing = timing_to_kernel_value(timing_raw, source_name=source_name)
    target_i = int(target or 0)
    rate_i = int(rate or 0)
    args = (int(p0 or 0), int(p1 or 0), int(p2 or 0), int(p3 or 0))

    pak_ref = link_pak_ref(
        primitive,
        timing,
        target_i,
        rate_i,
        args[0],
        args[1],
        args[2],
        args[3],
        source_name=source_name,
    )
    if pak_ref is not None:
        return (pak_ref,)

    entry_energy = _link_bft_o_t_entry_energy(
        primitive,
        target_i,
        rate_i,
        args[0],
        source_name=source_name,
    )
    if entry_energy is not None:
        return (entry_energy,)

    return (LinkedOp(
        primitive_to_op_name(primitive),
        timing,
        target_i,
        rate_i,
        args[0],
        args[1],
        args[2],
        args[3],
    ),)


def _link_bft_o_t_entry_energy(
    primitive: str,
    target: int,
    rate: int,
    base_id: int,
    *,
    source_name: str,
) -> LinkedOp | None:
    if primitive != P_BFT_O_T:
        return None
    if BUFFBASE_ORDER.get(base_id) != BFT_O_T:
        raise RuntimeError(f"{source_name!r} BFT_O_T row references non-BFT_O_T base_id {base_id}")
    base_params = BUFFBASE_PARAMS.get(base_id) or ()
    if len(base_params) < 7:
        raise RuntimeError(f"{source_name!r} BFT_O_T base_id {base_id} has short params {base_params!r}")
    amount = _energy_amount_from_effect_refs(_as_int_tuple(base_params[4]), source_name=source_name)
    source_kind = _param_int(base_params, 6)
    if source_kind == 0:
        skill_dam_type = _param_int(base_params, 0)
        element = _skill_dam_type_to_element(skill_dam_type, source_name=source_name)
        return LinkedOp(
            "op_entry_energy_from_element_count",
            TIMING_PAK_SDT,
            target,
            rate,
            element,
            amount,
        )
    if source_kind == 1 and _param_int(base_params, 0) == 0:
        return LinkedOp("op_entry_energy_from_counter_count", TIMING_PAK_SDT, target, rate, amount)
    raise RuntimeError(
        f"{source_name!r} BFT_O_T base_id {base_id} has unsupported source shape {base_params!r}"
    )


def _energy_amount_from_effect_refs(
    effect_refs: tuple[int, ...],
    *,
    source_name: str,
) -> int:
    amounts: set[int] = set()
    for effect_id in effect_refs:
        if EFFECT_ORDER.get(effect_id) != ET_CHANGE_ENERGY or EFFECT_TYPE.get(effect_id) != 3:
            raise RuntimeError(
                f"{source_name!r} BFT_O_T references non-ET_CHANGE_ENERGY effect {effect_id}"
            )
        amount = _param_int(EFFECT_PARAMS.get(effect_id) or (), 0)
        if amount <= 0:
            raise RuntimeError(
                f"{source_name!r} BFT_O_T references non-positive energy effect {effect_id}"
            )
        amounts.add(amount)
    if len(amounts) != 1:
        raise RuntimeError(f"{source_name!r} BFT_O_T has mixed energy amounts {sorted(amounts)!r}")
    return amounts.pop()


def _skill_dam_type_to_element(skill_dam_type: int, *, source_name: str) -> int:
    element = SKILL_DAM_TYPE_TO_ELEMENT.get(skill_dam_type)
    if element is None:
        raise RuntimeError(f"{source_name!r} references unmapped SkillDamType {skill_dam_type}")
    try:
        Element(int(element))
    except (TypeError, ValueError) as exc:
        raise RuntimeError(
            f"{source_name!r} SkillDamType {skill_dam_type} maps to invalid element {element}"
        ) from exc
    return int(element)


def _as_int_tuple(value: object) -> tuple[int, ...]:
    raw_values = value if isinstance(value, (list, tuple)) else (value,)
    out: list[int] = []
    for raw in raw_values:
        try:
            out.append(int(raw))
        except (TypeError, ValueError):
            continue
    return tuple(out)


def _param_int(params_raw: tuple, index: int, default: int = 0) -> int:
    if index >= len(params_raw):
        return default
    value = params_raw[index]
    if isinstance(value, tuple):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def timing_to_kernel_value(timing_raw: object, *, source_name: str) -> int:
    if not isinstance(timing_raw, str) or not timing_raw:
        raise RuntimeError(
            f"{source_name!r} produced non-keyed timing {timing_raw!r}; "
            "compiler rows must use battle_event:* or engine_hook:*"
        )
    battle_event = strip_prefix(timing_raw, BATTLE_EVENT_PREFIX)
    if battle_event is not None:
        value = BATTLE_EVENT_VALUES.get(battle_event)
        if value is None:
            raise RuntimeError(
                f"{source_name!r} produced unknown pak battle event timing {timing_raw!r}"
            )
        return int(value)
    engine_hook = strip_prefix(timing_raw, ENGINE_HOOK_PREFIX)
    if engine_hook is not None:
        value = ENGINE_HOOK_TIMINGS.get(engine_hook)
        if value is None:
            raise RuntimeError(
                f"{source_name!r} produced unknown engine timing hook {timing_raw!r}"
            )
        return int(value)
    raise RuntimeError(
        f"{source_name!r} produced unsupported timing key {timing_raw!r}; "
        "expected battle_event:* or engine_hook:*"
    )
