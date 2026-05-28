"""Resource and energy BUFF_CONF / EFFECT_CONF pak shape helpers."""

from __future__ import annotations

from roco.engine.artifacts.linked_op import LinkedOp
from roco.engine.artifacts.pak_ref_common import (
    EFFECT_ORDER,
    EFFECT_PARAMS,
    EFFECT_TYPE,
    _all_zero,
    _as_int_tuple,
    _base_rows,
    _gap,
    _op,
    _param_int,
    buff_type,
    effect_type,
)
from roco.engine.kernel.core.rows import TIMING_PAK_SDT


def link_life_drain_buff(buff_id: int, timing: int, target: int, rate: int) -> LinkedOp | None:
    rows = _base_rows(buff_id)
    if len(rows) != 1 or rows[0][1] != buff_type("BFT_BLOOD"):
        return None
    _base_id, _order, params = rows[0]
    if len(params) < 5 or not _all_zero(params[:4]) or not _all_zero(params[5:]):
        return None
    amount = _param_int(params, 4)
    if amount <= 0:
        return None
    return _op("op_life_drain", timing, target, rate, amount)


def energy_amount_from_effect_refs(effect_refs: tuple[int, ...], *, source_name: str) -> int:
    amounts: set[int] = set()
    for effect_id in effect_refs:
        if EFFECT_ORDER.get(effect_id) != effect_type("ET_CHANGE_ENERGY") or EFFECT_TYPE.get(effect_id) != 3:
            raise _gap(
                f"effect_ref:{effect_id}",
                "bft_o_t_non_energy_ref",
                source_name=source_name,
                timing=TIMING_PAK_SDT,
                target=0,
                rate=0,
                effect_id=effect_id,
            )
        amount = _param_int(EFFECT_PARAMS.get(effect_id) or (), 0)
        if amount <= 0:
            raise _gap(
                f"effect_ref:{effect_id}",
                "bft_o_t_non_positive_energy_ref",
                source_name=source_name,
                timing=TIMING_PAK_SDT,
                target=0,
                rate=0,
                effect_id=effect_id,
                amount=amount,
            )
        amounts.add(amount)
    if len(amounts) != 1:
        raise _gap(
            "effect_ref:*",
            "bft_o_t_mixed_energy_refs",
            source_name=source_name,
            timing=TIMING_PAK_SDT,
            target=0,
            rate=0,
            amounts=tuple(sorted(amounts)),
        )
    return amounts.pop()
