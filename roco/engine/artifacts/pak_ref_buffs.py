"""BUFF_CONF / BUFFBASE_CONF pak ref dispatcher."""
from __future__ import annotations
from roco.common.buffbase import pack_buff_delta_from_base_ids
from roco.engine.artifacts.linked_op import LinkedOp
from roco.engine.artifacts.pak_ref_buff_marks import _link_active_immunity_buff, _link_status_or_mark_buff, _link_zero_energy_auto_switch_buff
from roco.engine.artifacts.pak_ref_buff_modifiers import _energy_amount_from_effect_refs, _link_after_attack_response_buff, _link_after_attack_status_buff, _link_attack_cost_delta_buff, _link_conditional_hit_count_buff, _link_cute_bench_cost_reduce_buff, _link_damage_reduction_buff, _link_element_cost_reduce_buff, _link_force_switch_buff, _link_global_cost_delta_buff, _link_global_power_delta_buff, _link_heal_reversal_buff, _link_hit_count_delta_buff, _link_power_dynamic_buff, _link_specific_skill_power_bonus_buff, _link_team_skill_hit_count_buff, _link_transmission_buff
from roco.engine.artifacts.pak_ref_common import BUFF_BASE_IDS, BUFFBASE_ORDER, _as_int_tuple, _base_rows, _gap, _op, _param, _param_int, _skill_dam_type_to_element, buff_type
from roco.engine.kernel.op_rows import TIMING_PAK_SDT

def _link_assign_buff(buff_id: int, timing: int, target: int, rate: int, *, source_name: str, link_ref_id) -> tuple[LinkedOp, ...] | None:
    assign_rows = [(base_id, params) for base_id, order, params in _base_rows(buff_id) if order == buff_type('BFT_ASSIGN')]
    if not assign_rows:
        return None
    linked: list[LinkedOp] = []
    for base_id, params in assign_rows:
        refs = _as_int_tuple(_param(params, 0))
        assign_rate = _param_int(params, 1, 10000)
        target_code = _param_int(params, 2)
        if not refs:
            raise _gap(f'buff_ref:{buff_id}', 'assign_no_refs', source_name=source_name, timing=timing, target=target, rate=rate, buff_id=buff_id, buff_base_id=base_id)
        if assign_rate <= 0:
            raise _gap(f'buff_ref:{buff_id}', 'assign_zero_rate', source_name=source_name, timing=timing, target=target, rate=rate, buff_id=buff_id, buff_base_id=base_id, assign_rate=assign_rate)
        if target_code not in (0, 1, 2, 3, 4):
            raise _gap(f'buff_ref:{buff_id}', 'assign_condition_unsupported', source_name=source_name, timing=timing, target=target, rate=rate, buff_id=buff_id, buff_base_id=base_id, assigned_refs=refs, assign_target_or_condition=target_code)
        child_target = target_code or target
        child_rate = rate * assign_rate // 10000
        for ref_id in refs:
            linked.extend(link_ref_id(ref_id, timing, child_target, child_rate, source_name=source_name))
    return tuple(linked)

def _link_entry_energy_buff(buff_id: int, target: int, rate: int, *, source_name: str) -> LinkedOp | None:
    rows = _base_rows(buff_id)
    if len(rows) != 1 or rows[0][1] != buff_type('BFT_O_T'):
        return None
    base_id, _order, base_params = rows[0]
    if len(base_params) < 7:
        raise _gap(f'buff_ref:{buff_id}', 'bft_o_t_short_params', source_name=source_name, timing=TIMING_PAK_SDT, target=target, rate=rate, buff_id=buff_id, buff_base_id=base_id, base_params=base_params)
    amount = _energy_amount_from_effect_refs(_as_int_tuple(base_params[4]), source_name=source_name)
    source_kind = _param_int(base_params, 6)
    if source_kind == 0:
        element = _skill_dam_type_to_element(_param_int(base_params, 0), source_name=source_name)
        return _op('op_entry_energy_from_element_count', TIMING_PAK_SDT, target, rate, element, amount)
    if source_kind == 1 and _param_int(base_params, 0) == 0:
        return _op('op_entry_energy_from_counter_count', TIMING_PAK_SDT, target, rate, amount)
    raise _gap(f'buff_ref:{buff_id}', 'bft_o_t_source_shape_unsupported', source_name=source_name, timing=TIMING_PAK_SDT, target=target, rate=rate, buff_id=buff_id, buff_base_id=base_id, base_params=base_params)

def _link_generic_buff_delta(buff_id: int, timing: int, target: int, rate: int) -> LinkedOp | None:
    base_ids = tuple((int(v) for v in BUFF_BASE_IDS.get(buff_id) or () if v))
    packed = pack_buff_delta_from_base_ids(base_ids)
    if packed:
        return _op('op_self_buff', timing, target, rate, packed)
    return None

def link_buff_ref(buff_id: int, timing: int, target: int, rate: int, p0: int, p1: int, p2: int, p3: int, *, source_name: str, link_ref_id) -> tuple[LinkedOp, ...]:
    if buff_id not in BUFF_BASE_IDS:
        raise _gap(f'buff_ref:{buff_id}', 'buff_id_not_in_pak', source_name=source_name, timing=timing, target=target, rate=rate, buff_id=buff_id)
    assigned = _link_assign_buff(buff_id, timing, target, rate, source_name=source_name, link_ref_id=link_ref_id)
    if assigned is not None:
        return assigned
    stack_count = max(1, p0)
    linked = _link_status_or_mark_buff(buff_id, timing, target, rate, stack_count) or _link_zero_energy_auto_switch_buff(buff_id, timing, target, rate) or _link_active_immunity_buff(buff_id, timing, target, rate, source_name=source_name) or _link_team_skill_hit_count_buff(buff_id, timing, target, rate, stack_count, source_name=source_name) or _link_hit_count_delta_buff(buff_id, timing, target, rate, stack_count, source_name=source_name) or _link_heal_reversal_buff(buff_id, timing, target, rate, source_name=source_name) or _link_cute_bench_cost_reduce_buff(buff_id, timing, target, rate, source_name=source_name) or _link_conditional_hit_count_buff(buff_id, timing, target, rate, p0, source_name=source_name) or _link_transmission_buff(buff_id, timing, target, rate, p0, p1, p2, p3) or _link_entry_energy_buff(buff_id, target, rate, source_name=source_name) or _link_global_cost_delta_buff(buff_id, timing, target, rate) or _link_attack_cost_delta_buff(buff_id, timing, target, rate) or _link_element_cost_reduce_buff(buff_id, timing, target, rate) or _link_global_power_delta_buff(buff_id, timing, target, rate) or _link_after_attack_status_buff(buff_id, timing, target, rate) or _link_after_attack_response_buff(buff_id, timing, target, rate) or _link_damage_reduction_buff(buff_id, timing, target, rate) or _link_power_dynamic_buff(buff_id, timing, target, rate) or _link_specific_skill_power_bonus_buff(buff_id, timing, target, rate) or _link_force_switch_buff(buff_id, timing, target, rate) or _link_generic_buff_delta(buff_id, timing, target, rate)
    if linked is not None:
        return (linked,)
    raise _gap(f'buff_ref:{buff_id}', 'buff_shape_unsupported', source_name=source_name, timing=timing, target=target, rate=rate, buff_id=buff_id, base_ids=BUFF_BASE_IDS.get(buff_id) or (), base_orders=tuple((BUFFBASE_ORDER.get(base_id) for base_id in BUFF_BASE_IDS.get(buff_id) or ())))
