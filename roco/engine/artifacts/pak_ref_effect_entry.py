"""Entry-time EFFECT_CONF pak family matchers."""
from __future__ import annotations
from roco.common.buffbase import pack_buff_delta_from_base_ids
from roco.common.entry_sources import ENTRY_SOURCE_COUNTER, ENTRY_SOURCE_DEFENSE, ENTRY_SOURCE_ENEMY_SKILL_DAM_TYPE, ENTRY_SOURCE_ENEMY_SWITCH, ENTRY_SOURCE_EQUIPPED_ELEMENT, ENTRY_SOURCE_STATUS, ENTRY_SOURCE_USED_ELEMENT, entry_source_code
from roco.engine.artifacts.domains.status_mark.matchers import link_poison_to_mark_convert
from roco.engine.artifacts.linked_op import LinkedOp
from roco.engine.artifacts.pak_ref_common import BUFFBASE_ORDER, BUFFBASE_PARAMS, _all_regular_marks, _as_int_tuple, _base_ids_from_buff_ids, _element_mask, _inert, _is_burn_status, _is_internal_mark_sentinel, _op, _pack_buff_delta_from_buff_ids, _param, _param_int, _skill_dam_type_to_element, buff_type
from roco.engine.kernel.core.rows import TIMING_PAK_SDT

def _link_effect_buff_convert(_effect_id: int, params: tuple, timing: int, target: int, rate: int) -> LinkedOp | None:
    linked = link_poison_to_mark_convert(params, timing, target, rate)
    if linked is not None:
        return linked
    source_ids = _as_int_tuple(_param(params, 1))
    target_ids = _as_int_tuple(_param(params, 2))
    if _param_int(params, 0) != 0 or _param_int(params, 3) != 99 or _param_int(params, 4) != 0:
        return None
    if source_ids and _all_regular_marks(source_ids) and (len(target_ids) == 1):
        if _is_internal_mark_sentinel(target_ids[0]):
            return _op('op_dispel_marks', timing, target, rate)
    if len(source_ids) == 1 and _is_internal_mark_sentinel(source_ids[0]):
        if target_ids and len(set(target_ids)) == 1 and _is_burn_status(target_ids[0]):
            return _op('op_dispel_marks_to_burn', timing, target, rate, len(target_ids))
    return None

def _link_effect_buff_by_pack_pet_num(_effect_id: int, params: tuple, timing: int, target: int, rate: int) -> LinkedOp | None:
    timing = TIMING_PAK_SDT
    packed = _pack_buff_delta_from_buff_ids(_as_int_tuple(_param(params, 3)))
    if packed == 0:
        return None
    if _param_int(params, 1) == 2:
        return _op('op_entry_self_buff_by_fainted_count', timing, target, rate, packed)
    element = _param_int(params, 0, -1)
    if element >= 0:
        return _op('op_entry_self_buff_by_side_count', timing, target, rate, element, packed)
    return None

def _link_effect_entry_buff_if_energy(_effect_id: int, params: tuple, timing: int, target: int, rate: int) -> LinkedOp | None:
    timing = TIMING_PAK_SDT
    selector = _param_int(params, 2)
    if selector not in (1, 2):
        return None
    packed = _pack_buff_delta_from_buff_ids(_as_int_tuple(_param(params, 3)))
    if packed == 0:
        return None
    return _op('op_entry_self_buff_if_energy', timing, target, rate, selector, _param_int(params, 1), packed)

def _link_effect_hero(effect_id: int, params: tuple, timing: int, target: int, rate: int, *, source_name: str) -> LinkedOp | None:
    timing = TIMING_PAK_SDT
    if _param_int(params, 3) == 2:
        linked = _link_hero_event_count(effect_id, params, timing, target, rate)
        if linked is not None:
            return linked
    if _param_int(params, 3) != 1:
        return None
    buff_ids = _as_int_tuple(_param(params, 4))
    base_ids = _base_ids_from_buff_ids(buff_ids)
    linked = _link_entry_buff_per_used_skill_count(params, base_ids, timing, target, rate)
    if linked is not None:
        return linked
    source = _hero_count_source(params)
    if source is not None:
        linked = _link_raw_entry_element_mod_from_base_ids(source, base_ids, 'element', timing, target, rate, source_name=source_name)
        if linked is not None:
            return linked
    packed = pack_buff_delta_from_base_ids(base_ids)
    element = _param_int(params, 0, -1)
    if packed and element > 0:
        return _op('op_entry_self_buff_by_used_skill_count', timing, target, rate, element, packed)
    return None

def _link_hero_event_count(_effect_id: int, params: tuple, timing: int, target: int, rate: int) -> LinkedOp | None:
    packed = _pack_buff_delta_from_buff_ids(_as_int_tuple(_param(params, 4)))
    if packed == 0:
        return None
    skill_dam_type = _param_int(params, 0)
    if skill_dam_type > 0:
        source = entry_source_code(ENTRY_SOURCE_ENEMY_SKILL_DAM_TYPE, skill_dam_type)
        return _op('op_entry_self_buff_by_source_count', timing, target, rate, source, packed)
    if _param_int(params, 7) == 3:
        source = entry_source_code(ENTRY_SOURCE_ENEMY_SWITCH)
        return _op('op_entry_self_buff_by_source_count', timing, target, rate, source, packed)
    return None

def _link_entry_buff_per_used_skill_count(params: tuple, base_ids: tuple[int, ...], timing: int, target: int, rate: int) -> LinkedOp | None:
    element = _param_int(params, 0, -1)
    if element <= 0 or len(base_ids) != 1:
        return None
    base_id = base_ids[0]
    order = BUFFBASE_ORDER.get(base_id)
    base_params = BUFFBASE_PARAMS.get(base_id) or ()
    if order == buff_type('BFT_CHANGE_SKILL_ENERGY_COST') and len(base_params) >= 4:
        cost_delta = _param_int(base_params, 3)
        if cost_delta < 0:
            return _op('op_entry_buff_per_skill_count', timing, target, rate, element, 1, abs(cost_delta))
    if order == buff_type('BFT_INC_DAM_BY_SKILL') and len(base_params) >= 6:
        affected = _param_int(base_params, 0)
        mode = _param_int(base_params, 4)
        amount = _param_int(base_params, 5)
        if affected == 0 and mode == 2 and (amount > 0):
            return _op('op_entry_buff_per_skill_count', timing, target, rate, element, 2, amount)
    return None

def _hero_count_source(params: tuple) -> int | None:
    if _param_int(params, 7) == 1:
        return entry_source_code(ENTRY_SOURCE_COUNTER)
    category = _param_int(params, 2)
    if category == 2:
        return entry_source_code(ENTRY_SOURCE_STATUS)
    if category == 3:
        return entry_source_code(ENTRY_SOURCE_DEFENSE)
    element = _param_int(params, 0, -1)
    if element > 0:
        return entry_source_code(ENTRY_SOURCE_USED_ELEMENT, element)
    return None

def _link_effect_buff_by_equip_skill_num(effect_id: int, params: tuple, timing: int, target: int, rate: int, *, source_name: str) -> LinkedOp | None:
    timing = TIMING_PAK_SDT
    source_skill_dam_type = _param_int(params, 0, -1)
    buff_ids = _as_int_tuple(_param(params, 4))
    base_ids = _base_ids_from_buff_ids(buff_ids)
    if not base_ids:
        if not buff_ids or all(ref_id == 0 for ref_id in buff_ids):
            raise _inert(
                f'effect_ref:{effect_id}',
                'equip_skill_num_no_assigned_buff',
                source_name=source_name,
                timing=timing,
                target=target,
                rate=rate,
                effect_id=effect_id,
                effect_params=params,
            )
        return None
    source_element = _skill_dam_type_to_element(source_skill_dam_type, source_name=source_name)
    source_code = entry_source_code(ENTRY_SOURCE_EQUIPPED_ELEMENT, source_element)
    linked = _link_raw_entry_element_mod_from_base_ids(source_code, base_ids, 'skill_dam_type', timing, target, rate, source_name=source_name)
    if linked is None:
        raise RuntimeError(f'{source_name!r} EFFECT_CONF[{effect_id}] ET_BUFF_BY_EQUIP_SKILL_NUM has no supported BUFFBASE rows: {base_ids!r}')
    return linked

def _link_raw_entry_element_mod_from_base_ids(source_code: int, base_ids: tuple[int, ...], mask_kind: str, timing: int, target: int, rate: int, *, source_name: str) -> LinkedOp | None:
    parsed = [item for base_id in base_ids for item in (_decode_entry_element_base(base_id, mask_kind, source_name=source_name),) if item is not None]
    if not parsed:
        return None
    op_names = {op_name for _mask, _amount, op_name in parsed}
    amounts = {amount for _mask, amount, _op_name in parsed}
    if len(op_names) != 1 or len(amounts) != 1:
        raise RuntimeError(f'{source_name!r} raw entry element mod has mixed modes/amounts: {parsed!r}')
    mask = 0
    for item_mask, _amount, _op_name in parsed:
        mask |= item_mask
    _first_mask, amount, op_name = parsed[0]
    return _op(op_name, timing, target, rate, source_code, mask, amount)

def _decode_entry_element_base(base_id: int, mask_kind: str, *, source_name: str) -> tuple[int, int, str] | None:
    base_params = BUFFBASE_PARAMS.get(base_id) or ()
    order = BUFFBASE_ORDER.get(base_id)
    if order == buff_type('BFT_INC_DAM_BY_SKILL') and len(base_params) >= 6:
        mask = _element_mask(base_params[0], mask_kind)
        mode = _param_int(base_params, 4)
        amount = _param_int(base_params, 5)
        if mask and mode == 1 and (amount > 0):
            return (mask, amount, 'op_entry_element_power_bps_by_count')
        if mask and mode == 2 and (amount > 0):
            return (mask, amount, 'op_entry_element_power_flat_by_count')
    elif order == buff_type('BFT_CHANGE_SKILL_ENERGY_COST') and len(base_params) >= 4:
        mask = _element_mask(base_params[0], mask_kind)
        cost_delta = _param_int(base_params, 3)
        if mask and cost_delta < 0:
            return (mask, abs(cost_delta), 'op_entry_element_cost_reduce_by_count')
    elif order == buff_type('BFT_BUFF_AFTER_SKILL') and len(base_params) >= 5:
        mask = _element_mask(base_params[0], mask_kind)
        if mask:
            return (mask, 1, 'op_entry_element_poison_stacks_by_count')
    elif order == buff_type('BFT_DAMNUM_CHANGE') and len(base_params) >= 5:
        mask = _element_mask(base_params[0], mask_kind)
        categories = set(_as_int_tuple(base_params[1]))
        amount = _param_int(base_params, 4)
        if mask and categories == {2, 3} and (amount < 0):
            return (mask, abs(amount) // 100, 'op_entry_element_damage_reduce_by_count')
    elif order == buff_type('BFT_NINETY_EIGHT') and len(base_params) >= 2:
        mask = _element_mask(base_params[0], mask_kind)
        amount = _param_int(base_params, 1)
        if mask and amount < 0:
            return (mask, 1, 'op_entry_element_damage_resist_by_count')
    return None
