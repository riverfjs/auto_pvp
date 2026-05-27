"""BFT_CAST_SKILL_AFTER_ATTACK artifact linker."""

from __future__ import annotations

from roco.engine.artifacts.linked_op import ACTION_KIND_OP_LIST, LinkGapError, LinkInertError, LinkedAction
from roco.engine.artifacts.pak_ref_actions import child_ref_action
from roco.engine.artifacts.pak_ref_common import (
    BUFF_BASE_IDS,
    EFFECT_ORDER,
    EFFECT_PARAMS,
    BUFF_REDUCE_RULES,
    _as_int_tuple,
    _base_rows,
    _gap,
    _param,
    _param_int,
    buff_type,
    effect_type,
)
from roco.engine.kernel.core.rows import TARGET_ENEMY, TARGET_SELF


AfterAttackTriggerRow = tuple[int, int]
_RESPONSE_METADATA_PARAMS = (0, 0, 0, 0, 1, 0, 0, 0, 0, -1, 0, 0)


def after_attack_response_supported(buff_id: int, *, link_ref_id=None) -> bool:
    try:
        _after_attack_child_action(buff_id, timing=11, rate=10000, source_name=f"buff_ref:{buff_id}", link_ref_id=link_ref_id)
    except (LinkGapError, LinkInertError):
        return False
    return _response_duration_args(buff_id) is not None


def after_attack_response_duration_args(buff_id: int) -> tuple[int, int, int]:
    args = _response_duration_args(buff_id)
    if args is None:
        raise RuntimeError(f"BUFF_CONF[{buff_id}] has unsupported active response reduce rules")
    return args


def link_after_attack_buff_install(buff_id: int, timing: int, target: int, rate: int, *, link_ref_id, source_name: str):
    _after_attack_child_action(buff_id, timing=timing, rate=rate, source_name=source_name, link_ref_id=link_ref_id)
    args = after_attack_response_duration_args(buff_id)
    from roco.engine.artifacts.pak_ref_common import _op
    return _op("op_apply_active_buff", timing, target, rate, buff_id, *args)


def build_after_attack_trigger_rows(action_interner, *, link_ref_id) -> tuple[AfterAttackTriggerRow, ...]:
    rows: list[AfterAttackTriggerRow] = []
    for buff_id in sorted(BUFF_BASE_IDS):
        try:
            action = _after_attack_child_action(
                buff_id,
                timing=11,
                rate=10000,
                source_name=f"buff_ref:{buff_id}",
                link_ref_id=link_ref_id,
            )
        except (LinkGapError, LinkInertError):
            continue
        rows.append((buff_id, action_interner.intern(action)))
    return tuple(rows)


def _after_attack_child_action(buff_id: int, *, timing: int, rate: int, source_name: str, link_ref_id) -> LinkedAction:
    if link_ref_id is None:
        raise _gap(
            f"buff_ref:{buff_id}",
            "after_attack_link_ref_missing",
            source_name=source_name,
            timing=timing,
            target=TARGET_SELF,
            rate=rate,
            buff_id=buff_id,
        )
    rows = _response_rows(buff_id, source_name=source_name, timing=timing, rate=rate)
    ops = []
    for target, ref_ids, child_stack in rows:
        for ref_id in ref_ids:
            try:
                child = child_ref_action(
                    ref_id,
                    timing,
                    target,
                    rate,
                    source_name=source_name,
                    link_ref_id=link_ref_id,
                    stack_count=child_stack,
                )
            except LinkGapError:
                if _after_attack_child_inert(ref_id):
                    continue
                raise
            if child.kind != ACTION_KIND_OP_LIST:
                raise _gap(
                    f"buff_ref:{buff_id}",
                    "after_attack_nested_action_unsupported",
                    source_name=source_name,
                    timing=timing,
                    target=target,
                    rate=rate,
                    buff_id=buff_id,
                    ref_id=ref_id,
                )
            ops.extend(child.payload)
    if not ops:
        raise _gap(
            f"buff_ref:{buff_id}",
            "after_attack_no_runtime_ops",
            source_name=source_name,
            timing=timing,
            target=TARGET_SELF,
            rate=rate,
            buff_id=buff_id,
        )
    return LinkedAction(ACTION_KIND_OP_LIST, timing, TARGET_SELF, rate, tuple(ops), source_ref=buff_id, source_buff_id=buff_id)


def _response_rows(buff_id: int, *, source_name: str, timing: int, rate: int) -> tuple[tuple[int, tuple[int, ...], int], ...]:
    if _response_duration_args(buff_id) is None:
        raise _gap(
            f"buff_ref:{buff_id}",
            "after_attack_reduce_rules_unsupported",
            source_name=source_name,
            timing=timing,
            target=TARGET_SELF,
            rate=rate,
            buff_id=buff_id,
            reduce_rules=BUFF_REDUCE_RULES.get(buff_id) or (),
        )
    out: list[tuple[int, tuple[int, ...], int]] = []
    for base_id, order, params in _base_rows(buff_id):
        if _is_response_metadata_row(order, params):
            continue
        if order != buff_type("BFT_CAST_SKILL_AFTER_ATTACK"):
            raise _gap(
                f"buff_ref:{buff_id}",
                "after_attack_order_unsupported",
                source_name=source_name,
                timing=timing,
                target=TARGET_SELF,
                rate=rate,
                buff_id=buff_id,
                buff_base_id=base_id,
                base_order=order,
            )
        out.append(_parse_response_params(buff_id, base_id, params, source_name=source_name, timing=timing, rate=rate))
    if not out:
        raise _gap(f"buff_ref:{buff_id}", "after_attack_no_response_rows", source_name=source_name, timing=timing, target=TARGET_SELF, rate=rate, buff_id=buff_id)
    return tuple(out)


def _parse_response_params(buff_id: int, base_id: int, params: tuple, *, source_name: str, timing: int, rate: int) -> tuple[int, tuple[int, ...], int]:
    if len(params) < 9 or _as_int_tuple(params[0]) != (0,) or set(_as_int_tuple(params[1])) != {2, 3}:
        raise _shape_gap(buff_id, base_id, params, source_name, timing, rate)
    if _param_int(params, 2) != 0 or _param_int(params, 3) != 0:
        raise _shape_gap(buff_id, base_id, params, source_name, timing, rate)
    target_code = _param_int(params, 4)
    if target_code not in (-1, 0) or _param_int(params, 5) != 10000 or _param_int(params, 7) != 0:
        raise _shape_gap(buff_id, base_id, params, source_name, timing, rate)
    tail_flag = _param_int(params, 8)
    if tail_flag not in (0, 1):
        raise _shape_gap(buff_id, base_id, params, source_name, timing, rate)
    target = TARGET_ENEMY if target_code == -1 else TARGET_SELF
    refs = tuple(ref_id for ref_id in _as_int_tuple(params[6]) if ref_id > 0)
    if not refs:
        raise _shape_gap(buff_id, base_id, params, source_name, timing, rate)
    return target, refs, tail_flag


def _after_attack_child_inert(ref_id: int) -> bool:
    rows = _base_rows(ref_id)
    if len(rows) == 1:
        _base_id, order, params = rows[0]
        if order == buff_type("BFT_ATTR_CHANGE") and len(params) >= 3 and _params_all_zero(params[1:]):
            return True
        if order == buff_type("BFT_BUFF_AFTER_SKILL") and _buff_after_skill_purifies_zero_delta_sentinels(params):
            return True
    return False


def _buff_after_skill_purifies_zero_delta_sentinels(params: tuple) -> bool:
    if len(params) < 7:
        return False
    if not _params_all_zero(params[:4]) or _param_int(params, 5) != 0:
        return False
    effect_ids = _as_int_tuple(_param(params, 4))
    return len(effect_ids) == 1 and _effect_purifies_zero_delta_sentinels(effect_ids[0])


def _effect_purifies_zero_delta_sentinels(effect_id: int) -> bool:
    if EFFECT_ORDER.get(effect_id) != effect_type("ET_PURIFY"):
        return False
    params = EFFECT_PARAMS.get(effect_id) or ()
    if len(params) < 5:
        return False
    if _param_int(params, 0) != 3 or _param_int(params, 2) != 99:
        return False
    if _param_int(params, 3) != 99 or _param_int(params, 4) != 0:
        return False
    refs = _as_int_tuple(_param(params, 1))
    return bool(refs) and all(_zero_stat_delta_buff(ref_id) for ref_id in refs)


def _zero_stat_delta_buff(buff_id: int) -> bool:
    rows = _base_rows(buff_id)
    if len(rows) != 1:
        return False
    _base_id, order, params = rows[0]
    return order == buff_type("BFT_ATTR_CHANGE") and len(params) >= 3 and _params_all_zero(params[1:])


def _params_all_zero(values: tuple) -> bool:
    return all(all(raw == 0 for raw in _as_int_tuple(value)) for value in values)


def _shape_gap(buff_id: int, base_id: int, params: tuple, source_name: str, timing: int, rate: int):
    return _gap(
        f"buff_ref:{buff_id}",
        "after_attack_shape_unsupported",
        source_name=source_name,
        timing=timing,
        target=TARGET_SELF,
        rate=rate,
        buff_id=buff_id,
        buff_base_id=base_id,
        base_params=params,
    )


def _response_duration_args(buff_id: int) -> tuple[int, int, int] | None:
    rules = BUFF_REDUCE_RULES.get(buff_id) or ()
    if len(rules) != 1:
        return None
    reduce_type, params = rules[0]
    p0 = int(params[0]) if len(params) > 0 else 0
    p1 = int(params[1]) if len(params) > 1 else 0
    if int(reduce_type) == 13 and p0 == 999 and p1 == 0:
        return (13, p0, p1)
    if int(reduce_type) == 2 and p0 > 0:
        return (2, p0, p1)
    return None


def _is_response_metadata_row(order: int, params: tuple) -> bool:
    return order == buff_type("BFT_INC_DAM_BY_SKILL") and tuple(params) == _RESPONSE_METADATA_PARAMS
