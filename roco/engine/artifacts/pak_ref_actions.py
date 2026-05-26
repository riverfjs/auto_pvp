"""Helpers for lowering pak child refs into pure-data linked actions."""

from __future__ import annotations

from roco.engine.artifacts.linked_op import (
    ACTION_KIND_OP_LIST,
    LinkInertError,
    LinkedAction,
    LinkedOp,
)
from roco.engine.artifacts.pak_ref_common import _gap


LinkedRef = LinkedOp | LinkedAction


def child_ref_action(
    ref_id: int,
    timing: int,
    target: int,
    rate: int,
    *,
    source_name: str,
    link_ref_id,
    stack_count: int = 0,
) -> LinkedAction:
    try:
        linked = link_ref_id(
            ref_id,
            timing,
            target,
            rate,
            p0=stack_count,
            p1=0,
            p2=0,
            p3=0,
            source_name=source_name,
        )
    except LinkInertError:
        return LinkedAction(ACTION_KIND_OP_LIST, timing, target, rate, (), source_ref=ref_id)
    if len(linked) == 1 and isinstance(linked[0], LinkedAction):
        return linked[0]
    ops = tuple(item for item in linked if isinstance(item, LinkedOp))
    if len(ops) != len(linked) or not ops:
        raise _gap(
            f"pak_ref:{ref_id}",
            "child_ref_action_unsupported",
            source_name=source_name,
            timing=timing,
            target=target,
            rate=rate,
            ref_id=ref_id,
        )
    return LinkedAction(ACTION_KIND_OP_LIST, timing, target, rate, ops, source_ref=ref_id)
