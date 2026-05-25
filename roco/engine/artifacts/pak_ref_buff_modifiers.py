"""Numeric BUFFBASE pak shape matchers."""
from __future__ import annotations
from roco.common.constants import BPS
from roco.engine.artifacts.linked_op import LinkedOp
from roco.common.enums import StatusType
from roco.engine.artifacts.pak_ref_common import BUFF_BASE_IDS, BUFFBASE_ORDER, EFFECT_ORDER, EFFECT_PARAMS, EFFECT_TYPE, _all_skill_cost_reduce_amount, _all_zero, _as_int_tuple, _base_rows, _condition_refs_are_cute_effects, _condition_refs_are_poison_effects, _conditional_refs_and_grants, _element_mask, _gap, _grant_refs_are_hit_count_effects, _is_burn_status, _is_poison_status, _op, _pack_buff_delta_from_buff_ids, _param, _param_int, _single_int, _skill_dam_type_to_element, buff_type, effect_type
from roco.engine.kernel.effects.active_response import after_attack_response_duration_args, after_attack_response_supported
from roco.engine.kernel.core.rows import TARGET_ENEMY, TIMING_HOOK_BEFORE_MOVE, TIMING_PAK_BEFORE_HURT, TIMING_PAK_SDT

def _link_team_skill_hit_count_buff(buff_id: int, timing: int, target: int, rate: int, stack_count: int, *, source_name: str) -> LinkedOp | None:
    rows = _base_rows(buff_id)
    if len(rows) != 1 or rows[0][1] != buff_type('BFT_IMMUNE'):
        return None
    params = rows[0][2]
    if len(params) < 2 or _as_int_tuple(params[0]) != (3,):
        return None
    skill_ids = tuple((v for v in _as_int_tuple(params[1]) if v > 0))
    if len(skill_ids) > 1:
        return None
    skill_id = skill_ids[0] if skill_ids else 0
    return _op('op_hit_count_by_team_skill_count', timing, target, rate, stack_count, skill_id)

def _link_hit_count_delta_buff(buff_id: int, timing: int, target: int, rate: int, stack_count: int, *, source_name: str) -> LinkedOp | None:
    rows = _base_rows(buff_id)
    if len(rows) != 1 or rows[0][1] != buff_type('BFT_MULTIPLE_NUM'):
        return None
    params = rows[0][2]
    if len(params) < 3:
        return None
    amount = _single_int(params[0])
    mode = _single_int(params[2])
    if amount is None or amount == 0:
        return None
    if mode == 0:
        skill_ids = tuple((v for v in _as_int_tuple(params[1]) if v > 0))
        if len(skill_ids) > 3:
            return None
        padded = (skill_ids + (0, 0, 0))[:3]
        return _op('op_hit_count_delta', timing, target, rate, amount * stack_count, padded[0], padded[1], padded[2])
    if mode == 1:
        return _op('op_hit_count_percent_delta', timing, target, rate, amount)
    return None

def _link_heal_reversal_buff(buff_id: int, timing: int, target: int, rate: int, *, source_name: str) -> LinkedOp | None:
    rows = _base_rows(buff_id)
    if len(rows) != 1 or rows[0][1] != buff_type('BFT_O_FORTYSIX'):
        return None
    params = rows[0][2]
    if len(params) < 5 or _as_int_tuple(params[0]) != (24,) or _as_int_tuple(params[4]) != (-1,):
        return None
    trigger = _as_int_tuple(params[3])
    if len(trigger) < 2:
        return None
    return _op('op_anti_heal', timing, target, rate, max(1, trigger[1] // 10))


def _link_life_drain_buff(buff_id: int, timing: int, target: int, rate: int) -> LinkedOp | None:
    rows = _base_rows(buff_id)
    if len(rows) != 1 or rows[0][1] != buff_type('BFT_BLOOD'):
        return None
    _base_id, _order, params = rows[0]
    if len(params) < 5 or not _all_zero(params[:4]) or not _all_zero(params[5:]):
        return None
    amount = _param_int(params, 4)
    if amount <= 0:
        return None
    return _op('op_life_drain', timing, target, rate, amount)

def _link_cute_bench_cost_reduce_buff(buff_id: int, timing: int, target: int, rate: int, *, source_name: str) -> LinkedOp | None:
    for _base_id, order, params in _base_rows(buff_id):
        if order != buff_type('BFT_CHECK_BUFF_LAYER') or len(params) < 3:
            continue
        condition_refs = _as_int_tuple(params[0])
        target_refs = _as_int_tuple(params[2])
        if _as_int_tuple(params[1]) != (1,) or len(target_refs) != 1:
            continue
        if not condition_refs or not _condition_refs_are_cute_effects(condition_refs):
            continue
        amount = _all_skill_cost_reduce_amount(target_refs[0])
        if amount <= 0:
            continue
        return _op('op_cute_bench_cost_reduce', timing, target, rate, amount)
    return None

def _link_conditional_hit_count_buff(buff_id: int, timing: int, target: int, rate: int, amount: int, *, source_name: str) -> LinkedOp | None:
    base_ids = BUFF_BASE_IDS.get(buff_id) or ()
    if not base_ids or any((BUFFBASE_ORDER.get(base_id) != buff_type('BFT_NINETY_ONE') for base_id in base_ids)):
        return None
    if amount <= 0:
        return None
    condition_refs, grant_refs = _conditional_refs_and_grants(base_ids)
    if not _grant_refs_are_hit_count_effects(grant_refs):
        return None
    if _condition_refs_are_poison_effects(condition_refs):
        return _op('op_hit_count_per_poison_effect', TIMING_HOOK_BEFORE_MOVE, target, rate, amount)
    if _condition_refs_are_cute_effects(condition_refs):
        return _op('op_cute_hit_per_stack', TIMING_HOOK_BEFORE_MOVE, target, rate, amount)
    return None

def _link_transmission_buff(buff_id: int, timing: int, target: int, rate: int, p0: int, p1: int, p2: int, p3: int) -> LinkedOp | None:
    base_ids = BUFF_BASE_IDS.get(buff_id) or ()
    if not base_ids or any((BUFFBASE_ORDER.get(base_id) != buff_type('BFT_O_FIFTEEN') for base_id in base_ids)):
        return None
    if p0 > 0 and (p1 or p2 or p3):
        return _op('op_skill_mod', timing, target, rate, p0, p1, p2, p3)
    return None

def _link_global_cost_delta_buff(buff_id: int, timing: int, target: int, rate: int) -> LinkedOp | None:
    rows = _base_rows(buff_id)
    if not rows or any((row[1] != buff_type('BFT_CHANGE_SKILL_ENERGY_COST') for row in rows)):
        return None
    total = 0
    for _base_id, _order, params in rows:
        if len(params) < 7:
            return None
        if _as_int_tuple(params[0]) != (0,):
            return None
        if not _all_zero(params[1:3]) or _param_int(params, 4) != 0 or _param_int(params, 6) != 0:
            return None
        if _param_int(params, 5) not in (0, 1, 2, 3):
            return None
        amount = _param_int(params, 3)
        if amount == 0:
            return None
        total += amount
    if total == 0:
        return None
    return _op('op_global_cost_delta', timing, target, rate, total)

def _link_attack_cost_delta_buff(buff_id: int, timing: int, target: int, rate: int) -> LinkedOp | None:
    rows = _base_rows(buff_id)
    if not rows or any((row[1] != buff_type('BFT_CHANGE_SKILL_ENERGY_COST') for row in rows)):
        return None
    total = 0
    for _base_id, _order, params in rows:
        if len(params) < 7:
            return None
        if _as_int_tuple(params[0]) != (0,) or set(_as_int_tuple(params[1])) != {2, 3}:
            return None
        if not _all_zero(params[2:3]) or not _all_zero(params[4:]):
            return None
        amount = _param_int(params, 3)
        if amount == 0:
            return None
        total += amount
    if total == 0:
        return None
    return _op('op_attack_cost_delta', timing, target, rate, total)


def _link_element_cost_reduce_buff(buff_id: int, timing: int, target: int, rate: int) -> LinkedOp | None:
    rows = _base_rows(buff_id)
    if len(rows) != 1 or rows[0][1] != buff_type('BFT_CHANGE_SKILL_ENERGY_COST'):
        return None
    _base_id, _order, params = rows[0]
    if len(params) < 7:
        return None
    element_mask = _element_mask(params[0], 'skill_dam_type')
    if not element_mask:
        return None
    if not _all_zero(params[1:3]) or not _all_zero(params[4:]):
        return None
    amount = _param_int(params, 3)
    if amount >= 0:
        return None
    return _op('op_element_cost_reduce', timing, target, rate, element_mask, abs(amount))


def _link_after_attack_status_buff(buff_id: int, timing: int, target: int, rate: int) -> LinkedOp | None:
    rows = _base_rows(buff_id)
    if len(rows) != 1 or rows[0][1] != buff_type('BFT_BUFF_AFTER_SKILL'):
        return None
    _base_id, _order, params = rows[0]
    if len(params) < 7:
        return None
    if not _all_zero(params[:4]) or _param_int(params, 5) != 3:
        return None
    ref_ids = _as_int_tuple(params[4])
    if len(ref_ids) != 1:
        return None
    ref_id = ref_ids[0]
    stacks = _param_int(params, 6)
    if stacks <= 0:
        return None
    if _is_poison_status(ref_id):
        return _op('op_after_attack_status', TIMING_PAK_BEFORE_HURT, TARGET_ENEMY, rate, int(StatusType.POISON), stacks)
    if _is_burn_status(ref_id):
        return _op('op_after_attack_status', TIMING_PAK_BEFORE_HURT, TARGET_ENEMY, rate, int(StatusType.BURN), stacks)
    return None

def _link_after_skill_element_child_buff(buff_id: int, timing: int, target: int, rate: int, *, source_name: str) -> tuple[LinkedOp, ...] | None:
    rows = _base_rows(buff_id)
    if len(rows) != 1 or rows[0][1] != buff_type('BFT_BUFF_AFTER_SKILL'):
        return None
    _base_id, _order, params = rows[0]
    if len(params) < 7:
        return None
    raw_skill_dam_types = tuple(raw for raw in _as_int_tuple(params[0]) if raw > 0)
    if not raw_skill_dam_types:
        return None
    if not _all_zero(params[1:4]):
        return None
    elements = _skill_dam_type_elements(raw_skill_dam_types, source_name=source_name)
    if not elements:
        return None
    refs = tuple(ref_id for ref_id in _as_int_tuple(params[4]) if ref_id > 0)
    target_code = _param_int(params, 5)
    tail = _param(params, 6)

    if target_code == 0 and _all_zero((tail,)):
        if len(refs) == 1 and EFFECT_ORDER.get(refs[0]) == effect_type('ET_RECOVER'):
            amount = _param_int(EFFECT_PARAMS.get(refs[0]) or (), 1)
            if amount > 0:
                return tuple(
                    _op('op_on_skill_element_heal_hp', timing, target, rate, element, amount)
                    for element in elements
                )
        amount = _sum_all_skill_cost_reduce_amount(refs)
        if amount > 0:
            return tuple(
                _op('op_on_skill_element_cost_reduce', timing, target, rate, element, amount)
                for element in elements
            )
        hit_count = _sum_hit_count_delta_amount(refs)
        if hit_count > 0:
            return tuple(
                _op('op_on_skill_element_hit_count', timing, target, rate, element, hit_count)
                for element in elements
            )
        packed = _pack_buff_delta_from_buff_ids(refs)
        if packed:
            return tuple(
                _op('op_on_skill_element_buff', timing, target, rate, element, packed)
                for element in elements
            )

    if target_code == 2 and _all_zero((tail,)):
        if refs and all(_is_poison_status(ref_id) for ref_id in refs):
            return tuple(
                _op('op_on_skill_element_poison', timing, target, rate, element, len(refs))
                for element in elements
            )
        if refs and all(_is_burn_status(ref_id) for ref_id in refs):
            return tuple(
                _op('op_on_skill_element_burn', timing, target, rate, element, len(refs))
                for element in elements
            )
        if refs and all(_is_freeze_status(ref_id) for ref_id in refs):
            return tuple(
                _op('op_on_skill_element_freeze', timing, target, rate, element, len(refs))
                for element in elements
            )
    return None

def _sum_all_skill_cost_reduce_amount(buff_ids: tuple[int, ...]) -> int:
    if not buff_ids:
        return 0
    total = 0
    for buff_id in buff_ids:
        amount = _all_skill_cost_reduce_amount(buff_id)
        if amount <= 0:
            return 0
        total += amount
    return total

def _skill_dam_type_elements(skill_dam_types: tuple[int, ...], *, source_name: str) -> tuple[int, ...]:
    elements: list[int] = []
    for skill_dam_type in skill_dam_types:
        try:
            element = _skill_dam_type_to_element(skill_dam_type, source_name=source_name)
        except RuntimeError:
            return ()
        if element not in elements:
            elements.append(element)
    return tuple(elements)

def _sum_hit_count_delta_amount(buff_ids: tuple[int, ...]) -> int:
    if not buff_ids:
        return 0
    total = 0
    for buff_id in buff_ids:
        amount = _hit_count_delta_amount(buff_id)
        if amount <= 0:
            return 0
        total += amount
    return total

def _hit_count_delta_amount(buff_id: int) -> int:
    rows = _base_rows(buff_id)
    if len(rows) != 1 or rows[0][1] != buff_type('BFT_MULTIPLE_NUM'):
        return 0
    params = rows[0][2]
    if len(params) < 4:
        return 0
    amount = _single_int(params[0])
    if amount is None or amount <= 0:
        return 0
    if not _all_zero(params[1:]):
        return 0
    return amount

def _link_freeze_buff(buff_id: int, timing: int, target: int, rate: int) -> LinkedOp | None:
    rows = _base_rows(buff_id)
    if len(rows) != 1 or rows[0][1] != buff_type('BFT_FREEZE'):
        return None
    _base_id, _order, params = rows[0]
    if tuple(params) != (1, 500, 0, 50):
        return None
    return _op('op_freeze', timing, target, rate, 1)

def _is_freeze_status(buff_id: int) -> bool:
    rows = _base_rows(buff_id)
    return len(rows) == 1 and rows[0][1] == buff_type('BFT_FREEZE') and tuple(rows[0][2]) == (1, 500, 0, 50)

def _link_after_attack_response_buff(buff_id: int, timing: int, target: int, rate: int) -> LinkedOp | None:
    if not after_attack_response_supported(buff_id):
        return None
    reduce_type, p0, p1 = after_attack_response_duration_args(buff_id)
    return _op('op_apply_active_buff', timing, target, rate, buff_id, reduce_type, p0, p1)

def _link_global_power_delta_buff(buff_id: int, timing: int, target: int, rate: int) -> LinkedOp | None:
    rows = _base_rows(buff_id)
    if len(rows) != 1 or rows[0][1] != buff_type('BFT_INC_DAM_BY_SKILL'):
        return None
    _base_id, _order, params = rows[0]
    if len(params) < 12:
        return None
    if _as_int_tuple(params[0]) != (0,) or _as_int_tuple(params[1]) != (0,):
        return None
    if not _all_zero(params[2:4]) or not _all_zero(params[6:10]):
        return None
    if _param_int(params, 4) != 2 or _param_int(params, 10) != 1 or _param_int(params, 11) != 0:
        return None
    amount = _param_int(params, 5)
    if amount == 0:
        return None
    return _op('op_global_power_delta', timing, target, rate, amount)

def _link_damage_reduction_buff(buff_id: int, timing: int, target: int, rate: int) -> LinkedOp | None:
    rows = _base_rows(buff_id)
    if len(rows) != 1 or rows[0][1] != buff_type('BFT_DAMNUM_CHANGE'):
        return None
    _base_id, _order, params = rows[0]
    if len(params) < 5:
        return None
    if _as_int_tuple(params[0]) != (0,) or set(_as_int_tuple(params[1])) != {2, 3}:
        return None
    if not _all_zero(params[2:4]):
        return None
    if _param_int(params, 5) not in (0, 1) or not _all_zero(params[6:]):
        return None
    amount = _param_int(params, 4)
    if amount >= 0:
        return None
    return _op('op_damage_reduction', timing, target, rate, max(0, BPS + amount))

def _link_power_dynamic_buff(buff_id: int, timing: int, target: int, rate: int) -> LinkedOp | None:
    rows = _base_rows(buff_id)
    if len(rows) != 1 or rows[0][1] != buff_type('BFT_INC_DAM_BY_SKILL'):
        return None
    _base_id, _order, params = rows[0]
    if len(params) < 6:
        return None
    categories = _as_int_tuple(params[1])
    if categories not in ((0,), (2, 3), (3, 2)):
        return None
    if not _all_zero(params[2:4]) or not _all_zero(params[6:9]):
        return None
    if _param_int(params, 9) not in (0, 1) or not _all_zero(params[10:]):
        return None
    mode = _param_int(params, 4)
    amount = _param_int(params, 5)
    element_mask = 0
    if _as_int_tuple(params[0]) != (0,):
        element_mask = _element_mask(params[0], 'skill_dam_type')
        if not element_mask:
            return None
    if mode == 1 and amount > 0:
        if element_mask:
            return _op('op_power_dynamic_elements', timing, target, rate, element_mask, BPS + amount)
        return _op('op_power_dynamic', timing, target, rate, BPS + amount)
    if mode == 2 and amount != 0:
        if element_mask:
            return _op('op_power_dynamic_elements', timing, target, rate, element_mask, 0, amount)
        return _op('op_power_dynamic', timing, target, rate, 0, amount)
    return None


def _link_first_strike_power_buff(buff_id: int, timing: int, target: int, rate: int) -> LinkedOp | None:
    rows = _base_rows(buff_id)
    if len(rows) != 1 or rows[0][1] != buff_type('BFT_INC_DAM_BY_ATTACK_FIRST'):
        return None
    _base_id, _order, params = rows[0]
    if len(params) < 7:
        return None
    if _as_int_tuple(params[0]) != (0,) or _param_int(params, 2) != 0 or not _all_zero(params[4:]):
        return None
    categories = _as_int_tuple(params[1])
    if categories == (0,):
        category_scope = 0
    elif set(categories) == {2, 3}:
        category_scope = 1
    else:
        return None
    amount = _param_int(params, 3)
    if amount <= 0:
        return None
    return _op('op_first_strike_power_bps', timing, target, rate, category_scope, BPS + amount)


def _link_specific_skill_power_bonus_buff(buff_id: int, timing: int, target: int, rate: int) -> LinkedOp | None:
    rows = _base_rows(buff_id)
    if len(rows) != 1 or rows[0][1] != buff_type('BFT_STRENGTHEN_THE_SKILL'):
        return None
    _base_id, _order, params = rows[0]
    if len(params) < 8:
        return None
    skill_ids = _as_int_tuple(params[1])
    if _param_int(params, 0) != 7 or len(skill_ids) != 1 or skill_ids[0] <= 0:
        return None
    if _param_int(params, 2) != 1 or _param_int(params, 3) != 1:
        return None
    amount = _param_int(params, 4)
    if amount <= 0 or _param_int(params, 5) != 6 or not _all_zero(params[6:]):
        return None
    return _op('op_specific_skill_power_bonus', timing, target, rate, skill_ids[0], amount)


def _link_force_switch_buff(buff_id: int, timing: int, target: int, rate: int) -> LinkedOp | None:
    rows = _base_rows(buff_id)
    if len(rows) != 1 or rows[0][1] != buff_type('BFT_PET_TRANSE'):
        return None
    _base_id, _order, params = rows[0]
    if len(params) < 2 or not _all_zero(params[2:]):
        return None
    mode = _param_int(params, 1)
    if mode == 1:
        return _op('op_force_switch', timing, target, rate)
    if mode == 2:
        return _op('op_force_enemy_switch', timing, target, rate)
    return None

def _energy_amount_from_effect_refs(effect_refs: tuple[int, ...], *, source_name: str) -> int:
    amounts: set[int] = set()
    for effect_id in effect_refs:
        if EFFECT_ORDER.get(effect_id) != effect_type('ET_CHANGE_ENERGY') or EFFECT_TYPE.get(effect_id) != 3:
            raise _gap(f'effect_ref:{effect_id}', 'bft_o_t_non_energy_ref', source_name=source_name, timing=TIMING_PAK_SDT, target=0, rate=0, effect_id=effect_id)
        amount = _param_int(EFFECT_PARAMS.get(effect_id) or (), 0)
        if amount <= 0:
            raise _gap(f'effect_ref:{effect_id}', 'bft_o_t_non_positive_energy_ref', source_name=source_name, timing=TIMING_PAK_SDT, target=0, rate=0, effect_id=effect_id, amount=amount)
        amounts.add(amount)
    if len(amounts) != 1:
        raise _gap('effect_ref:*', 'bft_o_t_mixed_energy_refs', source_name=source_name, timing=TIMING_PAK_SDT, target=0, rate=0, amounts=tuple(sorted(amounts)))
    return amounts.pop()
