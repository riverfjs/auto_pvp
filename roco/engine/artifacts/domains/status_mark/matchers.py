"""Status/mark EFFECT_CONF matchers."""

from __future__ import annotations

from roco.engine.artifacts.linked_op import LinkedOp
from roco.engine.artifacts.pak_ref_common import _as_int_tuple, _is_poison_mark, _is_poison_status, _op, _param, _param_int


def link_poison_to_mark_convert(params: tuple, timing: int, target: int, rate: int) -> LinkedOp | None:
    source_ids = _as_int_tuple(_param(params, 1))
    target_ids = _as_int_tuple(_param(params, 2))
    if (
        _param_int(params, 0) == 0
        and len(source_ids) == 2
        and all(_is_poison_status(ref_id) for ref_id in source_ids)
        and len(target_ids) == 1
        and _is_poison_mark(target_ids[0])
        and _param_int(params, 3) == 99
        and _param_int(params, 4) == 1
    ):
        return _op("op_convert_poison_status_to_mark", timing, target, rate, len(source_ids), len(target_ids))
    return None

