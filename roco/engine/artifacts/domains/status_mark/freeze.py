"""Freeze BUFF_CONF pak shape matchers."""

from __future__ import annotations

from roco.engine.artifacts.linked_op import LinkedOp
from roco.engine.artifacts.pak_ref_common import _base_rows, _op, buff_type

_FREEZE_PARAMS = (1, 500, 0, 50)


def link_freeze_buff(buff_id: int, timing: int, target: int, rate: int) -> LinkedOp | None:
    rows = _base_rows(buff_id)
    if len(rows) != 1 or rows[0][1] != buff_type("BFT_FREEZE"):
        return None
    _base_id, _order, params = rows[0]
    if tuple(params) != _FREEZE_PARAMS:
        return None
    return _op("op_freeze", timing, target, rate, 1)


def is_freeze_status(buff_id: int) -> bool:
    rows = _base_rows(buff_id)
    return len(rows) == 1 and rows[0][1] == buff_type("BFT_FREEZE") and tuple(rows[0][2]) == _FREEZE_PARAMS
