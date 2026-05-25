"""Link compiler primitive rows to engine runtime rows."""

from __future__ import annotations

from typing import Iterable

from roco.common.primitive_keys import (
    BATTLE_EVENT_PREFIX,
    ENGINE_HOOK_PREFIX,
    effect_order_variant_key,
    strip_prefix,
)
from roco.common.entry_sources import ENTRY_SOURCE_EQUIPPED_ELEMENT, entry_source_code
from roco.common.enums import Element
from roco.engine.artifacts.skill_mod_modes import (
    ENTRY_MOD_COST_REDUCE,
    ENTRY_MOD_DAMAGE_REDUCE,
    ENTRY_MOD_DAMAGE_RESIST,
    ENTRY_MOD_POISON_STACKS,
    ENTRY_MOD_POWER_BPS,
    ENTRY_MOD_POWER_FLAT,
)
from roco.engine.artifacts.primitive_bindings import handler_const_from_primitive
from roco.engine.kernel.op_rows import TIMING_HOOK_BEFORE_MOVE
from roco.generated import handler_indices as hi
from roco.generated.battle_events import BATTLE_EVENT_VALUES
from roco.generated.buffbase_params import BUFFBASE_ORDER, BUFFBASE_PARAMS
from roco.generated.skill_dam_types import SKILL_DAM_TYPE_TO_ELEMENT
from roco.generated.static.lua_enums import BUFF_TYPE


PrimitiveRow = tuple[str, str, int, int, int, int, int, int]
RuntimeEffectRow = tuple[int, int, int, int, int, int, int, int]

ENGINE_HOOK_TIMINGS = {
    "before_move": TIMING_HOOK_BEFORE_MOVE,
}

RAW_ENTRY_ELEMENT_MOD_VARIANT = "raw_entry_element_skill_mod_by_count"
ENTRY_ELEMENT_MOD_VARIANT = "entry_element_skill_mod_by_count"
P_RAW_EQUIP_ELEMENT_MOD = effect_order_variant_key(
    "ET_BUFF_BY_EQUIP_SKILL_NUM",
    RAW_ENTRY_ELEMENT_MOD_VARIANT,
)
P_RAW_HERO_ELEMENT_MOD = effect_order_variant_key("ET_HERO", RAW_ENTRY_ELEMENT_MOD_VARIANT)
P_EQUIP_ELEMENT_MOD = effect_order_variant_key(
    "ET_BUFF_BY_EQUIP_SKILL_NUM",
    ENTRY_ELEMENT_MOD_VARIANT,
)
P_HERO_ELEMENT_MOD = effect_order_variant_key("ET_HERO", ENTRY_ELEMENT_MOD_VARIANT)

BFT_DAMNUM_CHANGE = int(BUFF_TYPE["BFT_DAMNUM_CHANGE"])
BFT_CHANGE_SKILL_ENERGY_COST = int(BUFF_TYPE["BFT_CHANGE_SKILL_ENERGY_COST"])
BFT_BUFF_AFTER_SKILL = int(BUFF_TYPE["BFT_BUFF_AFTER_SKILL"])
BFT_INC_DAM_BY_SKILL = int(BUFF_TYPE["BFT_INC_DAM_BY_SKILL"])
BFT_NINETY_EIGHT = int(BUFF_TYPE["BFT_NINETY_EIGHT"])


def primitive_to_handler_idx(primitive: str) -> int:
    """Resolve a primitive string to the current generated handler index."""

    const = handler_const_from_primitive(primitive)
    try:
        value = getattr(hi, const)
    except AttributeError as exc:
        raise RuntimeError(
            f"primitive {primitive!r} resolves to missing engine handler {const!r}"
        ) from exc
    if value <= 0:
        raise RuntimeError(f"primitive {primitive!r} resolved to invalid handler index {value}")
    return int(value)


def link_primitive_row(row: Iterable[object], *, source_name: str) -> RuntimeEffectRow:
    """Convert a compiler primitive row to an engine runtime effect row."""

    rows = link_primitive_rows(row, source_name=source_name)
    if len(rows) != 1:
        raise RuntimeError(
            f"{source_name!r} produced primitive row that linked to {len(rows)} runtime rows"
        )
    return rows[0]


def link_primitive_rows(row: Iterable[object], *, source_name: str) -> tuple[RuntimeEffectRow, ...]:
    """Convert a compiler primitive row to one or more engine runtime rows."""

    values = tuple(row)
    if len(values) != 8:
        raise RuntimeError(f"{source_name!r} produced malformed primitive row: {values!r}")
    primitive_raw, timing_raw, target, rate, p0, p1, p2, p3 = values
    primitive = str(primitive_raw)
    if not primitive:
        raise RuntimeError(f"{source_name!r} produced an empty effect primitive")
    timing = timing_to_kernel_value(timing_raw, source_name=source_name)
    raw_entry_mod = _link_raw_entry_element_mod(
        primitive,
        timing,
        int(target or 0),
        int(rate or 0),
        int(p0 or 0),
        int(p1 or 0),
        int(p2 or 0),
        int(p3 or 0),
        source_name=source_name,
    )
    if raw_entry_mod is not None:
        return (raw_entry_mod,)
    return ((
        primitive_to_handler_idx(primitive),
        timing,
        int(target or 0),
        int(rate or 0),
        int(p0 or 0),
        int(p1 or 0),
        int(p2 or 0),
        int(p3 or 0),
    ),)


def _link_raw_entry_element_mod(
    primitive: str,
    timing: int,
    target: int,
    rate: int,
    p0: int,
    p1: int,
    p2: int,
    p3: int,
    *,
    source_name: str,
) -> RuntimeEffectRow | None:
    if primitive == P_RAW_EQUIP_ELEMENT_MOD:
        source_element = _skill_dam_type_to_element(p0, source_name=source_name)
        source_code = entry_source_code(ENTRY_SOURCE_EQUIPPED_ELEMENT, source_element)
        mask_kind = "skill_dam_type"
        linked_primitive = P_EQUIP_ELEMENT_MOD
    elif primitive == P_RAW_HERO_ELEMENT_MOD:
        source_code = p0
        mask_kind = "element"
        linked_primitive = P_HERO_ELEMENT_MOD
    else:
        return None

    base_ids = tuple(base_id for base_id in (p1, p2, p3) if base_id > 0)
    parsed = [
        parsed_item
        for base_id in base_ids
        for parsed_item in (_decode_entry_element_base(base_id, mask_kind, source_name=source_name),)
        if parsed_item is not None
    ]
    if not parsed:
        raise RuntimeError(
            f"{source_name!r} raw entry element mod has no supported BUFFBASE rows: {base_ids!r}"
        )
    modes = {mode for _mask, _amount, mode in parsed}
    amounts = {amount for _mask, amount, _mode in parsed}
    if len(modes) != 1 or len(amounts) != 1:
        raise RuntimeError(
            f"{source_name!r} raw entry element mod has mixed modes/amounts: {parsed!r}"
        )
    mask = 0
    for item_mask, _amount, _mode in parsed:
        mask |= item_mask
    return (
        primitive_to_handler_idx(linked_primitive),
        timing,
        target,
        rate,
        source_code,
        mask,
        parsed[0][1],
        parsed[0][2],
    )


def _decode_entry_element_base(
    base_id: int,
    mask_kind: str,
    *,
    source_name: str,
) -> tuple[int, int, int] | None:
    base_params = BUFFBASE_PARAMS.get(base_id) or ()
    order = BUFFBASE_ORDER.get(base_id)
    if order == BFT_INC_DAM_BY_SKILL and len(base_params) >= 6:
        mask = _element_mask(base_params[0], mask_kind)
        mode = _param_int(base_params, 4)
        amount = _param_int(base_params, 5)
        if mask and mode in (ENTRY_MOD_POWER_BPS, ENTRY_MOD_POWER_FLAT) and amount > 0:
            return mask, amount, mode
    elif order == BFT_CHANGE_SKILL_ENERGY_COST and len(base_params) >= 4:
        mask = _element_mask(base_params[0], mask_kind)
        cost_delta = _param_int(base_params, 3)
        if mask and cost_delta < 0:
            return mask, abs(cost_delta), ENTRY_MOD_COST_REDUCE
    elif order == BFT_BUFF_AFTER_SKILL and len(base_params) >= 5:
        mask = _element_mask(base_params[0], mask_kind)
        if mask:
            return mask, 1, ENTRY_MOD_POISON_STACKS
    elif order == BFT_DAMNUM_CHANGE and len(base_params) >= 5:
        mask = _element_mask(base_params[0], mask_kind)
        categories = set(_as_int_tuple(base_params[1]))
        amount = _param_int(base_params, 4)
        if mask and categories == {2, 3} and amount < 0:
            return mask, abs(amount) // 100, ENTRY_MOD_DAMAGE_REDUCE
    elif order == BFT_NINETY_EIGHT and len(base_params) >= 2:
        mask = _element_mask(base_params[0], mask_kind)
        amount = _param_int(base_params, 1)
        if mask and amount < 0:
            return mask, 1, ENTRY_MOD_DAMAGE_RESIST
    return None


def _element_mask(value: object, mask_kind: str) -> int:
    mask = 0
    for raw in _as_int_tuple(value):
        if mask_kind == "skill_dam_type":
            element = SKILL_DAM_TYPE_TO_ELEMENT.get(raw)
            if element is None:
                continue
        else:
            if raw <= 0:
                continue
            element = raw
        if _valid_element(element):
            mask |= 1 << int(element)
    return mask


def _skill_dam_type_to_element(skill_dam_type: int, *, source_name: str) -> int:
    element = SKILL_DAM_TYPE_TO_ELEMENT.get(skill_dam_type)
    if element is None:
        raise RuntimeError(
            f"{source_name!r} references unmapped SkillDamType {skill_dam_type}"
        )
    if not _valid_element(element):
        raise RuntimeError(
            f"{source_name!r} SkillDamType {skill_dam_type} maps to invalid element {element}"
        )
    return int(element)


def _valid_element(element: object) -> bool:
    try:
        Element(int(element))
        return True
    except (TypeError, ValueError):
        return False


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
