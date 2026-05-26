"""Pak BFT_BUFF_AFTER_SKILL trigger matcher."""

from __future__ import annotations

from roco.engine.artifacts.action_payloads import TRIGGER_AFTER_SKILL
from roco.engine.artifacts.linked_op import (
    ACTION_KIND_OP_LIST,
    ACTION_KIND_TRIGGER_REGISTER,
    LinkGapError,
    LinkInertError,
    LinkedAction,
)
from roco.engine.artifacts.pak_ref_actions import child_ref_action
from roco.engine.artifacts.pak_ref_common import (
    BUFF_BASE_IDS,
    BUFF_REDUCE_RULES,
    _all_zero,
    _as_int_tuple,
    _base_rows,
    _gap,
    _param,
    _param_int,
    buff_type,
)
from roco.engine.kernel.core.rows import TARGET_ENEMY, TARGET_SELF


AfterSkillTriggerRow = tuple[int, int, tuple[int, ...]]


def link_after_skill_buff_install(
    buff_id: int,
    timing: int,
    target: int,
    rate: int,
    *,
    source_name: str,
    link_ref_id,
) -> LinkedAction | None:
    if _after_skill_base_params(buff_id) is None:
        return None
    _after_skill_child_action(buff_id, timing, rate, source_name=source_name, link_ref_id=link_ref_id)
    reduce_type, p0, p1 = _active_reduce_args(buff_id, source_name=source_name, timing=timing, target=target, rate=rate)
    return LinkedAction(
        ACTION_KIND_TRIGGER_REGISTER,
        timing,
        target,
        rate,
        (TRIGGER_AFTER_SKILL, target, buff_id, reduce_type, p0, p1),
        source_ref=buff_id,
        source_buff_id=buff_id,
    )


def build_after_skill_trigger_rows(action_interner, *, link_ref_id) -> tuple[AfterSkillTriggerRow, ...]:
    rows: list[AfterSkillTriggerRow] = []
    for buff_id in sorted(BUFF_BASE_IDS):
        params = _after_skill_base_params(buff_id)
        if params is None:
            continue
        try:
            action, raw_skill_dam_types = _after_skill_child_action(
                buff_id,
                timing=11,
                rate=10000,
                source_name=f"buff_ref:{buff_id}",
                link_ref_id=link_ref_id,
            )
            action_id = action_interner.intern(action)
        except (LinkGapError, LinkInertError):
            continue
        rows.append((buff_id, action_id, raw_skill_dam_types))
    return tuple(rows)


def _after_skill_base_params(buff_id: int) -> tuple | None:
    rows = _base_rows(buff_id)
    if len(rows) != 1 or rows[0][1] != buff_type("BFT_BUFF_AFTER_SKILL"):
        return None
    return rows[0][2]


def _after_skill_child_action(
    buff_id: int,
    timing: int,
    rate: int,
    *,
    source_name: str,
    link_ref_id,
) -> tuple[LinkedAction, tuple[int, ...]]:
    params = _after_skill_base_params(buff_id)
    if params is None:
        raise _gap(
            f"buff_ref:{buff_id}",
            "after_skill_missing_base",
            source_name=source_name,
            timing=timing,
            target=TARGET_SELF,
            rate=rate,
            buff_id=buff_id,
        )
    if len(params) < 7:
        raise _gap(
            f"buff_ref:{buff_id}",
            "after_skill_short_params",
            source_name=source_name,
            timing=timing,
            target=TARGET_SELF,
            rate=rate,
            buff_id=buff_id,
            base_params=params,
        )
    target_code = _param_int(params, 5)
    tail = _param_int(params, 6)
    if not _all_zero(params[1:4]) or (tail and target_code != 3):
        raise _gap(
            f"buff_ref:{buff_id}",
            "after_skill_shape_unsupported",
            source_name=source_name,
            timing=timing,
            target=TARGET_SELF,
            rate=rate,
            buff_id=buff_id,
            base_params=params,
        )
    raw_skill_dam_types = tuple(raw for raw in _as_int_tuple(_param(params, 0)) if raw > 0)
    child_refs = tuple(ref_id for ref_id in _as_int_tuple(_param(params, 4)) if ref_id > 0)
    if not child_refs:
        raise _gap(
            f"buff_ref:{buff_id}",
            "after_skill_no_child_refs",
            source_name=source_name,
            timing=timing,
            target=TARGET_SELF,
            rate=rate,
            buff_id=buff_id,
            base_params=params,
        )
    if target_code not in (0, 2, 3):
        raise _gap(
            f"buff_ref:{buff_id}",
            "after_skill_target_code_unsupported",
            source_name=source_name,
            timing=timing,
            target=TARGET_SELF,
            rate=rate,
            buff_id=buff_id,
            base_params=params,
            target_code=target_code,
        )
    child_target = _after_skill_child_target(target_code)
    children = tuple(
        child_ref_action(
            ref_id,
            timing,
            child_target,
            rate,
            source_name=source_name,
            link_ref_id=link_ref_id,
            stack_count=max(0, tail),
        )
        for ref_id in child_refs
    )
    if len(children) == 1:
        if children[0].kind == ACTION_KIND_OP_LIST and not children[0].payload:
            raise _gap(
                f"buff_ref:{buff_id}",
                "after_skill_all_children_inert",
                source_name=source_name,
                timing=timing,
                target=child_target,
                rate=rate,
                buff_id=buff_id,
                child_refs=child_refs,
            )
        return children[0], raw_skill_dam_types
    ops = tuple(op for child in children for op in _action_ops(child, source_name, timing, child_target, rate))
    if not ops:
        raise _gap(
            f"buff_ref:{buff_id}",
            "after_skill_all_children_inert",
            source_name=source_name,
            timing=timing,
            target=child_target,
            rate=rate,
            buff_id=buff_id,
            child_refs=child_refs,
        )
    return (
        LinkedAction(
            ACTION_KIND_OP_LIST,
            timing,
            child_target,
            rate,
            ops,
            source_ref=buff_id,
            source_buff_id=buff_id,
        ),
        raw_skill_dam_types,
    )


def _action_ops(action: LinkedAction, source_name: str, timing: int, target: int, rate: int) -> tuple:
    if action.kind != ACTION_KIND_OP_LIST:
        raise _gap(
            f"action:{action.source_ref}",
            "after_skill_nested_action_unsupported",
            source_name=source_name,
            timing=timing,
            target=target,
            rate=rate,
            ref_id=action.source_ref,
        )
    return tuple(action.payload)


def _after_skill_child_target(target_code: int) -> int:
    if target_code == 0:
        return TARGET_SELF
    return TARGET_ENEMY


def _active_reduce_args(
    buff_id: int,
    *,
    source_name: str,
    timing: int,
    target: int,
    rate: int,
) -> tuple[int, int, int]:
    rules = BUFF_REDUCE_RULES.get(buff_id) or ()
    if len(rules) != 1:
        raise _gap(
            f"buff_ref:{buff_id}",
            "after_skill_reduce_rules_unsupported",
            source_name=source_name,
            timing=timing,
            target=target,
            rate=rate,
            buff_id=buff_id,
            reduce_rules=rules,
        )
    reduce_type, params = rules[0]
    p0 = int(params[0]) if len(params) > 0 else 0
    p1 = int(params[1]) if len(params) > 1 else 0
    if int(reduce_type) == 13 and p0 == 999 and p1 == 0:
        return int(reduce_type), p0, p1
    if int(reduce_type) == 2 and p0 > 0:
        return int(reduce_type), p0, p1
    raise _gap(
        f"buff_ref:{buff_id}",
        "after_skill_reduce_rule_unsupported",
        source_name=source_name,
        timing=timing,
        target=target,
        rate=rate,
        buff_id=buff_id,
        reduce_rules=rules,
    )
