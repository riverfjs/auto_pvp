"""Shared raw pak shape helpers for pak ref linking."""
from __future__ import annotations
from roco.common.buffbase import pack_buff_delta_from_base_ids
from roco.common.enums import Element
from roco.engine.artifacts.linked_op import LinkGap, LinkGapError, LinkedOp
from roco.generated.buff_defs import BUFF_BASE_IDS, BUFF_REDUCE_RULES, BUFF_TYPE as BUFF_KIND
from roco.generated.buffbase_params import BUFFBASE_ORDER, BUFFBASE_PARAMS
from roco.generated.effect_params import EFFECT_ORDER, EFFECT_PARAMS, EFFECT_TYPE
from roco.generated.skill_dam_types import SKILL_DAM_TYPE_TO_ELEMENT
from roco.generated.static.lua_enums import BUFF_TYPE as LUA_BUFF_TYPE
from roco.generated.static.lua_enums import EFFECT_TYPE as LUA_EFFECT_TYPE

def buff_type(symbol: str) -> int:
    return int(LUA_BUFF_TYPE[symbol])

def effect_type(symbol: str) -> int:
    return int(LUA_EFFECT_TYPE[symbol])

def _op(op_name: str, timing: int, target: int, rate: int, p0: int=0, p1: int=0, p2: int=0, p3: int=0) -> LinkedOp:
    return LinkedOp(op_name, timing, target, rate, int(p0), int(p1), int(p2), int(p3))

def _gap(primitive: str, reason: str, *, source_name: str, timing: int, target: int, rate: int, effect_id: int | None=None, buff_id: int | None=None, **params: object) -> LinkGapError:
    return LinkGapError(LinkGap(primitive=primitive, reason=reason, source_name=source_name, effect_id=effect_id, buff_id=buff_id, timing=timing, target=target, rate=rate, params=params))

def _element_mask(value: object, mask_kind: str) -> int:
    mask = 0
    for raw in _as_int_tuple(value):
        if mask_kind == 'skill_dam_type':
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
        raise RuntimeError(f'{source_name!r} references unmapped SkillDamType {skill_dam_type}')
    if not _valid_element(element):
        raise RuntimeError(f'{source_name!r} SkillDamType {skill_dam_type} maps to invalid element {element}')
    return int(element)

def _valid_element(element: object) -> bool:
    try:
        Element(int(element))
        return True
    except (TypeError, ValueError):
        return False

def _base_rows(buff_id: int) -> tuple[tuple[int, int, tuple], ...]:
    rows: list[tuple[int, int, tuple]] = []
    for base_id in BUFF_BASE_IDS.get(buff_id) or ():
        rows.append((int(base_id), int(BUFFBASE_ORDER.get(base_id, 0) or 0), BUFFBASE_PARAMS.get(base_id) or ()))
    return tuple(rows)

def _has_base_order(buff_id: int, order: int) -> bool:
    return any((row_order == order for _base_id, row_order, _params in _base_rows(buff_id)))

def _has_order_params(rows: tuple[tuple[int, int, tuple], ...], order: int, predicate) -> bool:
    return any((row_order == order and predicate(params) for _base_id, row_order, params in rows))

def _is_poison_status(buff_id: int) -> bool:
    return _has_order_params(_base_rows(buff_id), buff_type('BFT_DAM'), lambda params: _param_int(params, 4) == 12)

def _is_burn_status(buff_id: int) -> bool:
    return _has_order_params(_base_rows(buff_id), buff_type('BFT_DAM'), lambda params: _param_int(params, 4) == 4)

def _is_poison_mark(buff_id: int) -> bool:
    return int(BUFF_KIND.get(buff_id, 0) or 0) == 4 and _is_poison_status(buff_id)

def _conditional_refs_and_grants(base_ids: tuple[int, ...]) -> tuple[tuple[int, ...], tuple[int, ...]]:
    condition_refs: list[int] = []
    grant_refs: list[int] = []
    for base_id in base_ids:
        params = BUFFBASE_PARAMS.get(base_id) or ()
        if len(params) > 1:
            condition_refs.extend(_as_int_tuple(params[1]))
        if len(params) > 3:
            grant_refs.extend(_as_int_tuple(params[3]))
    return (tuple(condition_refs), tuple(grant_refs))

def _grant_refs_are_hit_count_effects(ref_ids: tuple[int, ...]) -> bool:
    if not ref_ids:
        return False
    for ref_id in ref_ids:
        base_ids = BUFF_BASE_IDS.get(ref_id)
        if not base_ids:
            return False
        if not any((BUFFBASE_ORDER.get(base_id) == buff_type('BFT_O_EIGHT') for base_id in base_ids)):
            return False
    return True

def _condition_refs_are_poison_effects(ref_ids: tuple[int, ...]) -> bool:
    has_status = False
    has_mark = False
    for ref_id in ref_ids:
        if ref_id not in BUFF_BASE_IDS:
            return False
        if _is_poison_mark(ref_id):
            has_mark = True
        elif _is_poison_status(ref_id):
            has_status = True
        else:
            return False
    return has_status and has_mark

def _condition_refs_are_cute_effects(ref_ids: tuple[int, ...]) -> bool:
    if not ref_ids:
        return False
    for ref_id in ref_ids:
        base_ids = BUFF_BASE_IDS.get(ref_id)
        if not base_ids:
            return False
        if not all((BUFFBASE_ORDER.get(base_id) == buff_type('BFT_O_TWO') for base_id in base_ids)):
            return False
    return True

def _all_skill_cost_reduce_amount(buff_id: int) -> int:
    rows = _base_rows(buff_id)
    if len(rows) != 1 or rows[0][1] != buff_type('BFT_CHANGE_SKILL_ENERGY_COST'):
        return 0
    params = rows[0][2]
    if len(params) < 4 or _as_int_tuple(params[0]) != (0,):
        return 0
    cost_delta = _single_int(params[3])
    return abs(cost_delta) if cost_delta is not None and cost_delta < 0 else 0

def _all_regular_marks(buff_ids: tuple[int, ...]) -> bool:
    return bool(buff_ids) and all((int(BUFF_KIND.get(buff_id, 0) or 0) == 4 for buff_id in buff_ids))

def _is_internal_mark_sentinel(buff_id: int) -> bool:
    if int(BUFF_KIND.get(buff_id, 0) or 0) != 3:
        return False
    rules = BUFF_REDUCE_RULES.get(buff_id) or ()
    if not any((int(rule[0]) == 13 and len(rule[1]) >= 2 and (int(rule[1][1]) == 99) for rule in rules)):
        return False
    return _has_base_order(buff_id, buff_type('BFT_ATTR_CHANGE'))

def _pack_buff_delta_from_buff_ids(buff_ids: tuple[int, ...]) -> int:
    return pack_buff_delta_from_base_ids(_base_ids_from_buff_ids(buff_ids))

def _base_ids_from_buff_ids(buff_ids: tuple[int, ...]) -> tuple[int, ...]:
    out: list[int] = []
    for buff_id in buff_ids:
        out.extend((int(v) for v in BUFF_BASE_IDS.get(buff_id) or () if v))
    return tuple(out)

def _buff_refs_from_params(params: tuple) -> tuple[int, ...]:
    seen: list[int] = []
    for value in params:
        for raw in _as_int_tuple(value):
            if raw in BUFF_BASE_IDS and raw not in seen:
                seen.append(raw)
    return tuple(seen)

def _count_param_repeats(params: tuple, ref_id: int) -> int:
    best = 1
    for value in params:
        count = _as_int_tuple(value).count(ref_id)
        if count > best:
            best = count
    return best

def _param(params: tuple, index: int) -> object:
    return params[index] if index < len(params) else 0

def _single_int(value: object) -> int | None:
    values = _as_int_tuple(value)
    return values[0] if len(values) == 1 else None

def _all_zero(values: tuple) -> bool:
    return all((all((raw == 0 for raw in _as_int_tuple(value))) for value in values))

def _as_int_tuple(value: object) -> tuple[int, ...]:
    raw_values = value if isinstance(value, (list, tuple)) else (value,)
    out: list[int] = []
    for raw in raw_values:
        try:
            out.append(int(raw))
        except (TypeError, ValueError):
            continue
    return tuple(out)

def _param_int(params_raw: tuple, index: int, default: int=0) -> int:
    if index >= len(params_raw):
        return default
    value = params_raw[index]
    if isinstance(value, tuple):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
