"""Cute-condition BUFF_CONF pak shape matchers."""

from __future__ import annotations

from roco.engine.artifacts.linked_op import LinkedOp
from roco.engine.artifacts.pak_ref_common import (
    _all_skill_cost_reduce_amount,
    _as_int_tuple,
    _base_rows,
    _op,
    buff_type,
)


def link_cute_bench_cost_reduce_buff(
    buff_id: int,
    timing: int,
    target: int,
    rate: int,
    *,
    source_name: str,
) -> LinkedOp | None:
    from roco.engine.artifacts.pak_ref_common import _condition_refs_are_cute_effects

    for _base_id, order, params in _base_rows(buff_id):
        if order != buff_type("BFT_CHECK_BUFF_LAYER") or len(params) < 3:
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
        return _op("op_cute_bench_cost_reduce", timing, target, rate, amount)
    return None
