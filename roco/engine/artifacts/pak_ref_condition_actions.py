"""Pak BFT_CHECK_BUFF_LAYER conditional action matcher."""

from __future__ import annotations

from roco.common.enums import StatusType
from roco.common.packing import MarkIdx
from roco.engine.artifacts.action_payloads import (
    COND_KIND_ACTIVE_BUFF,
    COND_KIND_CUTE,
    COND_KIND_MARK,
    COND_KIND_STATUS,
    COND_REF_COUNT_AT_LEAST,
    COND_SCOPE_ENEMY,
)
from roco.engine.artifacts.linked_op import ACTION_KIND_CONDITIONAL, ACTION_KIND_OP_LIST, LinkedAction
from roco.engine.artifacts.pak_ref_actions import child_ref_action
from roco.engine.artifacts.pak_ref_common import (
    BUFF_KIND,
    _as_int_tuple,
    _base_rows,
    _gap,
    _is_burn_status,
    _is_poison_mark,
    _is_poison_status,
    _param,
    _param_int,
    buff_type,
)
from roco.engine.kernel.core.rows import TARGET_SELF


def link_check_buff_layer(buff_id: int, timing: int, target: int, rate: int, *, source_name: str, link_ref_id) -> LinkedAction | None:
    rows = _base_rows(buff_id)
    if not rows or any(order != buff_type("BFT_CHECK_BUFF_LAYER") for _base_id, order, _params in rows):
        return None
    child_actions: list[LinkedAction] = []
    for base_id, _order, params in rows:
        child_actions.append(_link_check_row(buff_id, base_id, params, timing, rate, source_name=source_name, link_ref_id=link_ref_id))
    if len(child_actions) == 1:
        return child_actions[0]
    ops = []
    for child in child_actions:
        if child.kind != ACTION_KIND_OP_LIST:
            raise _gap(
                f"buff_ref:{buff_id}",
                "check_buff_layer_nested_action_unsupported",
                source_name=source_name,
                timing=timing,
                target=target,
                rate=rate,
                buff_id=buff_id,
            )
        ops.extend(child.payload)
    return LinkedAction(ACTION_KIND_OP_LIST, timing, target, rate, tuple(ops), source_ref=buff_id, source_buff_id=buff_id)


def _link_check_row(buff_id: int, base_id: int, params: tuple, timing: int, rate: int, *, source_name: str, link_ref_id) -> LinkedAction:
    if len(params) < 6 or _param_int(params, 5) != 0:
        raise _gap(
            f"buff_ref:{buff_id}",
            "check_buff_layer_shape_unsupported",
            source_name=source_name,
            timing=timing,
            target=TARGET_SELF,
            rate=rate,
            buff_id=buff_id,
            buff_base_id=base_id,
            base_params=params,
        )
    target_code = _param_int(params, 4)
    if target_code != 2:
        raise _gap(
            f"buff_ref:{buff_id}",
            "check_buff_layer_target_code_unsupported",
            source_name=source_name,
            timing=timing,
            target=TARGET_SELF,
            rate=rate,
            buff_id=buff_id,
            buff_base_id=base_id,
            target_code=target_code,
            base_params=params,
        )
    specs = tuple(_condition_spec(ref_id, source_name=source_name, timing=timing, rate=rate) for ref_id in _as_int_tuple(_param(params, 0)))
    specs = tuple(dict.fromkeys(specs))
    if not specs:
        raise _gap(
            f"buff_ref:{buff_id}",
            "check_buff_layer_no_supported_conditions",
            source_name=source_name,
            timing=timing,
            target=TARGET_SELF,
            rate=rate,
            buff_id=buff_id,
            buff_base_id=base_id,
            base_params=params,
        )
    threshold = _param_int(params, 1)
    if threshold <= 0:
        raise _gap(
            f"buff_ref:{buff_id}",
            "check_buff_layer_bad_threshold",
            source_name=source_name,
            timing=timing,
            target=TARGET_SELF,
            rate=rate,
            buff_id=buff_id,
            buff_base_id=base_id,
            threshold=threshold,
        )
    child_refs = tuple(ref_id for ref_id in _as_int_tuple(_param(params, 2)) if ref_id > 0)
    if not child_refs:
        raise _gap(
            f"buff_ref:{buff_id}",
            "check_buff_layer_no_child_refs",
            source_name=source_name,
            timing=timing,
            target=TARGET_SELF,
            rate=rate,
            buff_id=buff_id,
            buff_base_id=base_id,
        )
    child_stack = max(0, _param_int(params, 3))
    child_actions = tuple(
        child_ref_action(
            ref_id,
            timing,
            TARGET_SELF,
            rate,
            source_name=source_name,
            link_ref_id=link_ref_id,
            stack_count=child_stack,
        )
        for ref_id in child_refs
    )
    if any(child.kind != ACTION_KIND_OP_LIST for child in child_actions):
        raise _gap(
            f"buff_ref:{buff_id}",
            "check_buff_layer_child_action_unsupported",
            source_name=source_name,
            timing=timing,
            target=TARGET_SELF,
            rate=rate,
            buff_id=buff_id,
            buff_base_id=base_id,
            child_refs=child_refs,
        )
    ops = tuple(op for child in child_actions for op in child.payload)
    if not ops:
        raise _gap(
            f"buff_ref:{buff_id}",
            "check_buff_layer_child_action_unsupported",
            source_name=source_name,
            timing=timing,
            target=TARGET_SELF,
            rate=rate,
            buff_id=buff_id,
            buff_base_id=base_id,
            child_refs=child_refs,
        )
    return LinkedAction(
        ACTION_KIND_CONDITIONAL,
        timing,
        TARGET_SELF,
        rate,
        (
            COND_REF_COUNT_AT_LEAST,
            specs,
            threshold,
            LinkedAction(ACTION_KIND_OP_LIST, timing, TARGET_SELF, rate, ops, source_ref=buff_id, source_buff_id=buff_id),
        ),
        source_ref=buff_id,
        source_buff_id=buff_id,
    )


def _condition_spec(ref_id: int, *, source_name: str, timing: int, rate: int) -> tuple[int, int, int]:
    if _is_poison_status(ref_id):
        return (COND_KIND_STATUS, int(StatusType.POISON), COND_SCOPE_ENEMY)
    if _is_burn_status(ref_id):
        return (COND_KIND_STATUS, int(StatusType.BURN), COND_SCOPE_ENEMY)
    if _is_freeze_status(ref_id):
        return (COND_KIND_STATUS, int(StatusType.FREEZE), COND_SCOPE_ENEMY)
    mark = _mark_idx(ref_id)
    if mark is not None:
        return (COND_KIND_MARK, int(mark), COND_SCOPE_ENEMY)
    if _is_cute(ref_id):
        return (COND_KIND_CUTE, 0, COND_SCOPE_ENEMY)
    if ref_id > 0 and _has_active_lifecycle(ref_id):
        return (COND_KIND_ACTIVE_BUFF, ref_id, COND_SCOPE_ENEMY)
    raise _gap(
        f"buff_ref:{ref_id}",
        "check_buff_layer_condition_ref_unsupported",
        source_name=source_name,
        timing=timing,
        target=TARGET_SELF,
        rate=rate,
        ref_id=ref_id,
    )


def _is_freeze_status(buff_id: int) -> bool:
    return any(order == buff_type("BFT_FREEZE") and tuple(params) == (1, 500, 0, 50) for _base_id, order, params in _base_rows(buff_id))


def _mark_idx(buff_id: int) -> MarkIdx | None:
    rows = _base_rows(buff_id)
    if _is_poison_mark(buff_id):
        return MarkIdx.POISON
    if any(order == buff_type("BFT_NINETY_FOUR") for _base_id, order, _params in rows):
        return MarkIdx.METEOR
    if any(order == buff_type("BFT_SPIKES") and _param_int(params, 0) == 1001005 for _base_id, order, params in rows):
        return MarkIdx.THORN
    return None


def _is_cute(buff_id: int) -> bool:
    rows = _base_rows(buff_id)
    return bool(rows) and all(order == buff_type("BFT_O_TWO") for _base_id, order, _params in rows)


def _has_active_lifecycle(buff_id: int) -> bool:
    return int(BUFF_KIND.get(buff_id, 0) or 0) == 3 and bool(_base_rows(buff_id))
