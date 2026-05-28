"""Zero-energy active buff BUFF_CONF pak shape matchers."""

from __future__ import annotations

from roco.engine.artifacts.linked_op import LinkedOp
from roco.engine.artifacts.pak_ref_common import BUFF_BASE_IDS, _base_rows, _op, _single_int, buff_type


def link_zero_energy_auto_switch_buff(buff_id: int, timing: int, target: int, rate: int) -> LinkedOp | None:
    for _base_id, order, params in _base_rows(buff_id):
        if order == buff_type("BFT_IMMUNE") and len(params) >= 2:
            if _single_int(params[0]) == 6 and (_single_int(params[1]) or 0) in BUFF_BASE_IDS:
                return _op("op_auto_switch_on_zero_energy", timing, target, rate)
    return None
