"""Ability-domain BUFF_CONF matchers."""

from __future__ import annotations

from roco.common.constants import BPS
from roco.engine.artifacts.linked_op import LinkedOp
from roco.engine.artifacts.pak_ref_common import _all_zero, _as_int_tuple, _base_rows, _inert, _op, _param_int, buff_type
from roco.engine.kernel.core.rows import TIMING_HOOK_BEFORE_MOVE


def link_ability_effect_buff(buff_id: int, timing: int, target: int, rate: int, *, source_name: str) -> LinkedOp | None:
    linked = _link_jiahuo_hit_count(buff_id, target, rate)
    if linked is not None:
        return linked
    linked = _link_life_trick(buff_id, target, rate)
    if linked is not None:
        return linked
    linked = _link_burn_decay_growth_marker(buff_id, timing, target, rate, source_name=source_name)
    if linked is not None:
        return linked
    return None


def _link_jiahuo_hit_count(buff_id: int, target: int, rate: int) -> LinkedOp | None:
    rows = _base_rows(buff_id)
    if len(rows) != 1 or rows[0][1] != buff_type("BFT_INC_DAM_BY_SKILL"):
        return None
    _base_id, _order, params = rows[0]
    if tuple(params) == (0, 0, 0, 0, 1, 0, 1043005, 0, 0, 0, 0, 0):
        return _op("op_stat_scale_hits_per_hp_lost", TIMING_HOOK_BEFORE_MOVE, target, rate, 2)
    return None


def _link_life_trick(buff_id: int, target: int, rate: int) -> LinkedOp | None:
    rows = _base_rows(buff_id)
    if len(rows) != 1 or rows[0][1] != buff_type("BFT_INC_DAM_BY_SKILL"):
        return None
    _base_id, _order, params = rows[0]
    if len(params) < 12:
        return None
    if (
        _as_int_tuple(params[0]) == (0,)
        and set(_as_int_tuple(params[1])) == {2, 3}
        and _all_zero(params[2:4])
        and _param_int(params, 4) == 1
        and _param_int(params, 5) == BPS
        and _param_int(params, 6) == 1001003
        and _all_zero(params[7:])
    ):
        return _op("op_life_trick_power_hp_cost", TIMING_HOOK_BEFORE_MOVE, target, rate, BPS, BPS // 2)
    return None


def _link_burn_decay_growth_marker(buff_id: int, timing: int, target: int, rate: int, *, source_name: str) -> LinkedOp | None:
    rows = _base_rows(buff_id)
    if len(rows) != 1 or rows[0][1] != buff_type("BFT_O_ELEVEN"):
        return None
    base_id, _order, params = rows[0]
    if tuple(params) == (20070020, -1, 0):
        raise _inert(
            f"buff_ref:{buff_id}",
            "represented_by_ability_flag_burn_decay_growth",
            source_name=source_name,
            timing=timing,
            target=target,
            rate=rate,
            buff_id=buff_id,
            buff_base_id=base_id,
            base_params=params,
        )
    return None

