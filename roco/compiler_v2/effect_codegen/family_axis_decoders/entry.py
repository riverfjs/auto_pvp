"""Switch-in and history-count pak effect-order decoders."""

from __future__ import annotations

from roco.common.buffbase import pack_buff_delta_from_buff_ids
from roco.common.entry_sources import (
    ENTRY_SOURCE_COUNTER,
    ENTRY_SOURCE_DEFENSE,
    ENTRY_SOURCE_ENEMY_SKILL_DAM_TYPE,
    ENTRY_SOURCE_ENEMY_SWITCH,
    ENTRY_SOURCE_EQUIPPED_ELEMENT,
    ENTRY_SOURCE_STATUS,
    ENTRY_SOURCE_USED_ELEMENT,
    entry_source_code,
)
from roco.common.skill_mod_modes import (
    ENTRY_MOD_COST_REDUCE,
    ENTRY_MOD_POISON_STACKS,
    ENTRY_MOD_POWER_BPS,
    ENTRY_MOD_POWER_FLAT,
)
from roco.compiler_v2.effect_codegen.buffbase_source import BUFFBASE_ORDER, BUFFBASE_PARAMS
from roco.compiler_v2.effect_codegen.outcomes import EmitOutcome
from roco.compiler_v2.effect_codegen.params import extract_int_list, safe_int

from roco.compiler_v2.effect_codegen.family_axis_decoders.common import (
    COUNT_FAINTED_ALLY,
    SWITCH_IN_TIMING,
    emit_effect_order,
    emit_effect_order_variant,
    params,
)


def decode_buff_by_pack_pet_num(rec: dict, buff_conf: dict[int, dict]) -> tuple[EmitOutcome, str] | None:
    params_raw = params(rec)
    packed = pack_buff_delta_from_buff_ids(extract_int_list(params_raw, 3), buff_conf)
    if packed == 0:
        return None
    if safe_int(params_raw, 1) == 2:
        return emit_effect_order_variant(
            "ET_BUFF_BY_PACK_PET_NUM",
            "entry_self_buff_by_side_count",
            COUNT_FAINTED_ALLY,
            packed,
        ), SWITCH_IN_TIMING
    element = safe_int(params_raw, 0, -1)
    if element >= 0:
        return emit_effect_order_variant(
            "ET_BUFF_BY_PACK_PET_NUM",
            "entry_self_buff_by_side_count",
            element,
            packed,
        ), SWITCH_IN_TIMING
    return None


def decode_entry_static_buff(rec: dict, buff_conf: dict[int, dict]) -> tuple[EmitOutcome, str] | None:
    packed = pack_buff_delta_from_buff_ids(extract_int_list(params(rec), 0), buff_conf)
    if packed == 0:
        return None
    return emit_effect_order("ET_BUFF_BY_CHANGE_TIMES", packed), SWITCH_IN_TIMING


def decode_entry_buff_if_energy(rec: dict, buff_conf: dict[int, dict]) -> tuple[EmitOutcome, str] | None:
    params_raw = params(rec)
    selector = safe_int(params_raw, 2)
    if selector not in (1, 2):
        return None
    packed = pack_buff_delta_from_buff_ids(extract_int_list(params_raw, 3), buff_conf)
    if packed == 0:
        return None
    return emit_effect_order_variant(
        "ET_LIMIT_FIGHT_BY_HP",
        "entry_self_buff_if_energy",
        selector,
        safe_int(params_raw, 1),
        packed,
    ), SWITCH_IN_TIMING


def decode_hero_entry(rec: dict, buff_conf: dict[int, dict]) -> tuple[EmitOutcome, str] | None:
    params_raw = params(rec)
    event_count_buff = _decode_hero_event_count_buff(params_raw, buff_conf)
    if event_count_buff is not None:
        return event_count_buff
    if safe_int(params_raw, 3) != 1:
        return None
    skill_count_mod = _decode_entry_buff_per_used_skill_count(params_raw, buff_conf)
    if skill_count_mod is not None:
        return skill_count_mod
    source = _hero_count_source(params_raw)
    if source is not None:
        element_mod = _decode_entry_element_mod(
            _base_ids_from_buff_ids(extract_int_list(params_raw, 4), buff_conf),
            source,
            "ET_HERO",
        )
        if element_mod is not None:
            return element_mod
    packed = pack_buff_delta_from_buff_ids(extract_int_list(params_raw, 4), buff_conf)
    if packed == 0:
        return None
    element = safe_int(params_raw, 0, -1)
    if element > 0:
        return emit_effect_order_variant(
            "ET_HERO",
            "entry_self_buff_by_used_skill_count",
            element,
            packed,
        ), SWITCH_IN_TIMING
    return None


def decode_buff_by_equip_skill_num(rec: dict, buff_conf: dict[int, dict]) -> tuple[EmitOutcome, str] | None:
    params_raw = params(rec)
    source_element = safe_int(params_raw, 0, -1)
    if source_element <= 0:
        return None
    return _decode_entry_element_mod(
        _base_ids_from_buff_ids(extract_int_list(params_raw, 4), buff_conf),
        entry_source_code(ENTRY_SOURCE_EQUIPPED_ELEMENT, source_element),
        "ET_BUFF_BY_EQUIP_SKILL_NUM",
    )


def _decode_hero_event_count_buff(
    params_raw: list,
    buff_conf: dict[int, dict],
) -> tuple[EmitOutcome, str] | None:
    if safe_int(params_raw, 3) != 2:
        return None
    packed = pack_buff_delta_from_buff_ids(extract_int_list(params_raw, 4), buff_conf)
    if packed == 0:
        return None
    skill_dam_type = safe_int(params_raw, 0)
    if skill_dam_type > 0:
        return emit_effect_order_variant(
            "ET_HERO",
            "entry_self_buff_by_source_count",
            entry_source_code(ENTRY_SOURCE_ENEMY_SKILL_DAM_TYPE, skill_dam_type),
            packed,
        ), SWITCH_IN_TIMING
    if safe_int(params_raw, 7) == 3:
        return emit_effect_order_variant(
            "ET_HERO",
            "entry_self_buff_by_source_count",
            entry_source_code(ENTRY_SOURCE_ENEMY_SWITCH),
            packed,
        ), SWITCH_IN_TIMING
    return None


def _decode_entry_buff_per_used_skill_count(
    params_raw: list,
    buff_conf: dict[int, dict],
) -> tuple[EmitOutcome, str] | None:
    element = safe_int(params_raw, 0, -1)
    if element <= 0:
        return None
    base_ids = _base_ids_from_buff_ids(extract_int_list(params_raw, 4), buff_conf)
    if len(base_ids) != 1:
        return None
    base_id = base_ids[0]
    order = BUFFBASE_ORDER.get(base_id)
    base_params = BUFFBASE_PARAMS.get(base_id) or ()
    if order == 32 and len(base_params) >= 4:
        cost_delta = _param_int(base_params, 3)
        if cost_delta < 0:
            return emit_effect_order_variant(
                "ET_HERO",
                "entry_buff_per_skill_count",
                element,
                1,
                abs(cost_delta),
            ), SWITCH_IN_TIMING
    if order == 23 and len(base_params) >= 6:
        affected = base_params[0]
        mode = _param_int(base_params, 4)
        amount = _param_int(base_params, 5)
        if affected == 0 and mode == 2 and amount > 0:
            return emit_effect_order_variant(
                "ET_HERO",
                "entry_buff_per_skill_count",
                element,
                2,
                amount,
            ), SWITCH_IN_TIMING
    return None


def _decode_entry_element_mod(
    base_ids: list[int],
    source_code: int,
    effect_order_symbol: str,
) -> tuple[EmitOutcome, str] | None:
    parsed: list[tuple[int, int, int]] = []
    for base_id in base_ids:
        base_params = BUFFBASE_PARAMS.get(base_id) or ()
        order = BUFFBASE_ORDER.get(base_id)
        if order == 23 and len(base_params) >= 6:
            mask = _element_mask(base_params[0])
            mode = _param_int(base_params, 4)
            amount = _param_int(base_params, 5)
            if mask and mode in (ENTRY_MOD_POWER_BPS, ENTRY_MOD_POWER_FLAT) and amount > 0:
                parsed.append((mask, amount, mode))
        elif order == 32 and len(base_params) >= 4:
            mask = _element_mask(base_params[0])
            cost_delta = _param_int(base_params, 3)
            if mask and cost_delta < 0:
                parsed.append((mask, abs(cost_delta), ENTRY_MOD_COST_REDUCE))
        elif order == 35 and len(base_params) >= 5:
            mask = _element_mask(base_params[0])
            if mask:
                parsed.append((mask, 1, ENTRY_MOD_POISON_STACKS))
    if not parsed:
        return None
    modes = {mode for _mask, _amount, mode in parsed}
    amounts = {amount for _mask, amount, _mode in parsed}
    if len(modes) != 1 or len(amounts) != 1:
        return None
    mask = 0
    for item_mask, _amount, _mode in parsed:
        mask |= item_mask
    amount = parsed[0][1]
    mode = parsed[0][2]
    return emit_effect_order_variant(
        effect_order_symbol,
        "entry_element_skill_mod_by_count",
        source_code,
        mask,
        amount,
        mode,
    ), SWITCH_IN_TIMING


def _hero_count_source(params_raw: list) -> int | None:
    if safe_int(params_raw, 7) == 1:
        return entry_source_code(ENTRY_SOURCE_COUNTER)
    category = safe_int(params_raw, 2)
    if category == 2:
        return entry_source_code(ENTRY_SOURCE_STATUS)
    if category == 3:
        return entry_source_code(ENTRY_SOURCE_DEFENSE)
    element = safe_int(params_raw, 0, -1)
    if element > 0:
        return entry_source_code(ENTRY_SOURCE_USED_ELEMENT, element)
    return None


def _element_mask(value: object) -> int:
    values = value if isinstance(value, tuple) else (value,)
    mask = 0
    for raw in values:
        try:
            element = int(raw)
        except (TypeError, ValueError):
            continue
        if element > 0:
            mask |= 1 << element
    return mask


def _base_ids_from_buff_ids(buff_ids: list[int], buff_conf: dict[int, dict]) -> list[int]:
    out: list[int] = []
    for buff_id in buff_ids:
        rec = buff_conf.get(buff_id) or {}
        for base_id in rec.get("buff_base_ids") or ():
            if base_id:
                out.append(int(base_id))
    return out


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
