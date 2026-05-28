"""Active-buff immunity/install BUFF_CONF pak shape matchers."""

from __future__ import annotations

from roco.engine.artifacts.linked_op import LinkedOp
from roco.engine.artifacts.pak_ref_common import BUFF_BASE_IDS, BUFF_KIND, BUFF_REDUCE_RULES, BUFFBASE_ORDER, _op, buff_type


def link_active_immunity_buff(
    buff_id: int,
    timing: int,
    target: int,
    rate: int,
    *,
    source_name: str,
) -> LinkedOp | None:
    if int(BUFF_KIND.get(buff_id, 0) or 0) != 3:
        return None
    if not any(BUFFBASE_ORDER.get(base_id) == buff_type("BFT_IMMUNE") for base_id in BUFF_BASE_IDS.get(buff_id) or ()):
        return None
    rules = BUFF_REDUCE_RULES.get(buff_id) or ()
    if not rules:
        return None
    if len(rules) != 1:
        return None
    reduce_type, params = rules[0]
    if int(reduce_type) != 13:
        return None
    p0 = params[0] if len(params) > 0 else 0
    p1 = params[1] if len(params) > 1 else 0
    return _op("op_apply_active_buff", timing, target, rate, buff_id, int(reduce_type), int(p0), int(p1))
