"""Cute stack BUFF_CONF pak shape matchers."""

from __future__ import annotations

from roco.engine.artifacts.linked_op import LinkedOp
from roco.engine.artifacts.pak_ref_common import _base_rows, _op, buff_type
from roco.engine.kernel.core.rows import TARGET_ENEMY, TARGET_SELF

_CUTE_STACK_PARAMS = (1, 0, 0, 1, 1)


def link_cute_stack_buff(buff_id: int, timing: int, target: int, rate: int) -> LinkedOp | None:
    rows = _base_rows(buff_id)
    if len(rows) != 1:
        return None
    _base_id, order, params = rows[0]
    if order != buff_type("BFT_O_TWO") or tuple(params) != _CUTE_STACK_PARAMS:
        return None
    if target == TARGET_SELF:
        return _op("op_cute_gain", timing, target, rate, 1)
    if target == TARGET_ENEMY:
        return _op("op_cute_enemy_gain", timing, target, rate, 1)
    return None
