"""Status, mark, and active-buff pak shape matchers."""
from __future__ import annotations
from roco.engine.artifacts.linked_op import LinkedOp
from roco.engine.artifacts.pak_ref_common import BUFF_BASE_IDS, BUFF_KIND, BUFF_REDUCE_RULES, BUFFBASE_ORDER, EFFECT_ORDER, EFFECT_PARAMS, _as_int_tuple, _base_rows, _has_base_order, _has_order_params, _is_burn_status, _is_poison_mark, _is_poison_status, _op, _param, _param_int, _single_int, buff_type, effect_type

def _link_status_or_mark_buff(buff_id: int, timing: int, target: int, rate: int, stack_count: int) -> LinkedOp | None:
    kind = int(BUFF_KIND.get(buff_id, 0) or 0)
    if kind == 2:
        switch_lock = _link_switch_lock_buff(buff_id, timing, target, rate)
        if switch_lock is not None:
            return switch_lock
        if _is_poison_status(buff_id):
            return _op('op_poison', timing, target, rate, stack_count)
        if _is_burn_status(buff_id):
            return _op('op_burn', timing, target, rate, stack_count)
        if _has_base_order(buff_id, buff_type('BFT_ABSORB')):
            return _op('op_leech', timing, target, rate, stack_count)
    if kind == 4:
        purify_mark = _link_mark_purify_carrier(buff_id, timing, target, rate)
        if purify_mark is not None:
            return purify_mark
        op_name = _mark_op_name_by_shape(buff_id)
        if op_name is not None:
            return _op(op_name, timing, target, rate, stack_count)
    return None

def _link_mark_purify_carrier(buff_id: int, timing: int, target: int, rate: int) -> LinkedOp | None:
    rows = _base_rows(buff_id)
    if len(rows) != 1 or rows[0][1] != buff_type('BFT_IMMUNE'):
        return None
    params = rows[0][2]
    if len(params) < 2 or _single_int(params[0]) != 3:
        return None
    effect_id = _single_int(params[1])
    if effect_id and _effect_purifies_regular_marks(effect_id):
        return _op('op_dispel_marks', timing, target, rate)
    return None

def _effect_purifies_regular_marks(effect_id: int) -> bool:
    if EFFECT_ORDER.get(effect_id) != effect_type('ET_PURIFY'):
        return False
    params = EFFECT_PARAMS.get(effect_id) or ()
    if len(params) < 5:
        return False
    if _param_int(params, 0) != 3 or _param_int(params, 2) != 99:
        return False
    if _param_int(params, 3) != 99 or _param_int(params, 4) != 0:
        return False
    refs = _as_int_tuple(_param(params, 1))
    return bool(refs) and all(int(BUFF_KIND.get(ref_id, 0) or 0) == 4 for ref_id in refs)

def _mark_op_name_by_shape(buff_id: int) -> str | None:
    rows = _base_rows(buff_id)
    if _is_poison_mark(buff_id):
        return 'op_poison_mark'
    if _has_order_params(rows, buff_type('BFT_CHANGE_SKILL_ENERGY_COST'), lambda p: _param_int(p, 3) == -1):
        return 'op_moisture_mark'
    if _has_order_params(rows, buff_type('BFT_NINETY_FOUR'), lambda _p: True):
        return 'op_meteor_mark'
    if _has_order_params(rows, buff_type('BFT_ATTR_CHANGE'), lambda p: _param_int(p, 0) == 6 and _param_int(p, 2) < 0):
        return 'op_slow_mark'
    if _has_order_params(rows, buff_type('BFT_ASSIGN'), lambda p: _param_int(p, 0) == 1019001):
        return 'op_solar_mark'
    if _has_order_params(rows, buff_type('BFT_INC_DAM_BY_ATTACK_FIRST'), lambda p: _param_int(p, 3) > 0):
        return 'op_wind_mark'
    if _has_order_params(rows, buff_type('BFT_NINETY_THREE'), lambda p: _param_int(p, 4) == 1 and _param_int(p, 5) == 10):
        return 'op_charge_mark'
    if _has_order_params(rows, buff_type('BFT_SPIKES'), lambda p: _param_int(p, 0) == 1019011):
        return 'op_spirit_mark'
    if _has_order_params(rows, buff_type('BFT_SPIKES'), lambda p: _param_int(p, 0) == 1001005):
        return 'op_thorn_mark'
    if _has_order_params(rows, buff_type('BFT_STRENGTHEN_THE_SKILL'), lambda p: _param_int(p, 0) == 6):
        return 'op_dragon_mark'
    has_skill_cost_plus = _has_order_params(rows, buff_type('BFT_CHANGE_SKILL_ENERGY_COST'), lambda p: _param_int(p, 3) > 0)
    has_power_plus = _has_order_params(rows, buff_type('BFT_INC_DAM_BY_SKILL'), lambda p: _param_int(p, 4) == 1 and _param_int(p, 5) > 0)
    if has_skill_cost_plus and has_power_plus:
        return 'op_momentum_mark'
    if has_power_plus:
        return 'op_attack_mark'
    return None

def _link_switch_lock_buff(buff_id: int, timing: int, target: int, rate: int) -> LinkedOp | None:
    rows = _base_rows(buff_id)
    if not rows:
        return None
    ban_rows = [params for _base_id, order, params in rows if order == buff_type('BFT_BAN')]
    immune_rows = [params for _base_id, order, params in rows if order == buff_type('BFT_IMMUNE')]
    if len(ban_rows) != 1 or _as_int_tuple(ban_rows[0]) != (1,):
        return None
    if len(immune_rows) != len(rows) - 1:
        return None
    if any(_as_int_tuple(params) != (5, 48) for params in immune_rows):
        return None
    rules = BUFF_REDUCE_RULES.get(buff_id) or ()
    if len(rules) != 1:
        return None
    reduce_type, reduce_params = rules[0]
    if int(reduce_type) != 2 or len(reduce_params) < 1:
        return None
    turns = int(reduce_params[0])
    if turns <= 0:
        return None
    return _op('op_switch_lock', timing, target, rate, turns)

def _link_active_immunity_buff(buff_id: int, timing: int, target: int, rate: int, *, source_name: str) -> LinkedOp | None:
    if int(BUFF_KIND.get(buff_id, 0) or 0) != 3:
        return None
    if not any((BUFFBASE_ORDER.get(base_id) == buff_type('BFT_IMMUNE') for base_id in BUFF_BASE_IDS.get(buff_id) or ())):
        return None
    rules = BUFF_REDUCE_RULES.get(buff_id) or ()
    if not rules:
        return None
    if len(rules) != 1:
        return None
    reduce_type, params = rules[0]
    if int(reduce_type) != 13:
        return None
    p0 = params[0] if len(params) > 0 else 0
    p1 = params[1] if len(params) > 1 else 0
    return _op('op_apply_active_buff', timing, target, rate, buff_id, int(reduce_type), int(p0), int(p1))

def _link_zero_energy_auto_switch_buff(buff_id: int, timing: int, target: int, rate: int) -> LinkedOp | None:
    for _base_id, order, params in _base_rows(buff_id):
        if order == buff_type('BFT_IMMUNE') and len(params) >= 2:
            if _single_int(params[0]) == 6 and (_single_int(params[1]) or 0) in BUFF_BASE_IDS:
                return _op('op_auto_switch_on_zero_energy', timing, target, rate)
    return None
