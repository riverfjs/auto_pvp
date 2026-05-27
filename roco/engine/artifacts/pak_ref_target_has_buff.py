"""Pak BFT_TARGET_HAS_BUFF matcher.

Only pak shapes that can be proven from generated static tables are linked
here.  Rows whose semantics only exist in source descriptions stay as explicit
gaps until a generated desc-derived semantic table exists.
"""

from __future__ import annotations

from roco.engine.artifacts.linked_op import LinkedOp
from roco.engine.artifacts.pak_ref_common import (
    BUFF_KIND,
    _all_zero,
    _as_int_tuple,
    _base_rows,
    _gap,
    _op,
    _param,
    _param_int,
    buff_type,
)
from roco.generated.pak.battle_globals import BATTLE_GLOBAL_LISTS


_TARGET_HAS_BUFF = buff_type("BFT_TARGET_HAS_BUFF")
_BFT_ATTR_CHANGE = buff_type("BFT_ATTR_CHANGE")
_BFT_NINETY_FOUR = buff_type("BFT_NINETY_FOUR")


def link_target_has_buff(buff_id: int, timing: int, target: int, rate: int, *, source_name: str) -> tuple[LinkedOp, ...] | None:
    rows = _base_rows(buff_id)
    if not rows or any(order != _TARGET_HAS_BUFF for _base_id, order, _params in rows):
        return None

    linked: list[LinkedOp] = []
    seen: set[LinkedOp] = set()
    for base_id, _order, params in rows:
        op = _link_target_has_buff_row(buff_id, base_id, params, timing, target, rate, source_name=source_name)
        if op in seen:
            continue
        seen.add(op)
        linked.append(op)
    if not linked:
        raise _gap(
            f"buff_ref:{buff_id}",
            "target_has_buff_shape_unsupported",
            source_name=source_name,
            timing=timing,
            target=target,
            rate=rate,
            buff_id=buff_id,
            base_ids=tuple(base_id for base_id, _order, _params in rows),
        )
    return tuple(linked)


def _link_target_has_buff_row(
    buff_id: int,
    base_id: int,
    params: tuple,
    timing: int,
    target: int,
    rate: int,
    *,
    source_name: str,
) -> LinkedOp:
    if _is_mark_total_to_meteor_shape(params):
        return _op("op_meteor_mark_by_target_mark_total", timing, target, rate, 1)
    if _is_sequence_sentinel_shape(params):
        raise _gap(
            f"buff_ref:{buff_id}",
            "target_has_buff_sequence_sentinel_unsupported",
            source_name=source_name,
            timing=timing,
            target=target,
            rate=rate,
            buff_id=buff_id,
            buff_base_id=base_id,
            base_params=params,
        )
    desc_derived = _link_desc_derived_shape(buff_id, params, timing, target, rate)
    if desc_derived is not None:
        return desc_derived
    if _uses_desc_only_zero_delta_sentinel(params):
        raise _gap(
            f"buff_ref:{buff_id}",
            "target_has_buff_desc_sentinel_unresolved",
            source_name=source_name,
            timing=timing,
            target=target,
            rate=rate,
            buff_id=buff_id,
            buff_base_id=base_id,
            base_params=params,
        )
    if _is_target_positive_buff_power(params):
        return _op("op_power_bps_by_target_positive_buff_layers", timing, target, rate, _param_int(params, 10))
    if _is_meteor_mark_power(params):
        return _op(
            "op_power_bps_by_target_meteor_mark",
            timing,
            target,
            rate,
            _param_int(params, 6),
            _param_int(params, 10),
        )
    raise _gap(
        f"buff_ref:{buff_id}",
        "target_has_buff_row_shape_unsupported",
        source_name=source_name,
        timing=timing,
        target=target,
        rate=rate,
        buff_id=buff_id,
        buff_base_id=base_id,
        base_params=params,
    )


def _common_power_tail(params: tuple, *, mode: int, amount_nonzero: bool = True) -> bool:
    if len(params) < 11:
        return False
    if _param_int(params, 0) != 0 or _param_int(params, 1) != 0 or _param_int(params, 2) != 0:
        return False
    if _param_int(params, 4) != 2 or _param_int(params, 5) != 0:
        return False
    if _param_int(params, 7) != 1 or _param_int(params, 8) != 0 or _param_int(params, 9) != mode:
        return False
    return _param_int(params, 10) != 0 if amount_nonzero else True


def _is_mark_total_to_meteor_shape(params: tuple) -> bool:
    refs = _as_int_tuple(_param(params, 3))
    return (
        len(params) >= 11
        and _param_int(params, 0) == 0
        and _param_int(params, 1) == 0
        and _param_int(params, 2) == 0
        and refs
        and _all_mark_refs(refs)
        and _param_int(params, 4) in _meteor_mark_refs()
        and _param_int(params, 5) == 3
        and _param_int(params, 6) == 0
        and _param_int(params, 7) == 2
        and _param_int(params, 8) == 0
        and _param_int(params, 9) == 1
        and _param_int(params, 10) == 0
    )


def _is_sequence_sentinel_shape(params: tuple) -> bool:
    refs = _as_int_tuple(_param(params, 3))
    return (
        len(params) >= 11
        and refs
        and all(_is_zero_delta_sentinel(ref_id) for ref_id in refs)
        and _param_int(params, 8) == 0
        and _param_int(params, 9) == 1
        and _param_int(params, 10) == 0
    )


def _uses_desc_only_zero_delta_sentinel(params: tuple) -> bool:
    refs = _as_int_tuple(_param(params, 3))
    if not refs or not any(_is_zero_delta_sentinel(ref_id) for ref_id in refs):
        return False
    return _param_int(params, 9) in (1, 2)


def _is_target_positive_buff_power(params: tuple) -> bool:
    return tuple(params) == (0, 1, 0, 0, 2, 0, 0, 1, 0, 2, 1000)


def _link_desc_derived_shape(buff_id: int, params: tuple, timing: int, target: int, rate: int) -> LinkedOp | None:
    # These ids use zero-delta sentinel refs in pak; the sentinel proves the
    # family row but not the human meaning.  The meaning was derived from source
    # descriptions during development, then bound here by exact pak id+params.
    if buff_id == 20630120 and tuple(params) == (0, 0, 0, 20010814, 2, 0, 0, 1, 0, 1, 10):
        return _op("op_power_flat_by_target_skill_type_count", timing, target, rate, 10)
    if buff_id == 20630190 and tuple(params) == (0, 0, 0, 20340060, 2, 0, 0, 1, 0, 2, 1000):
        return _op("op_power_bps_by_target_skill_total_cost", timing, target, rate, 1000)
    if buff_id == 20630160 and tuple(params) == (0, 0, 0, 20010854, 2, 0, 0, 1, 0, 2, 10000):
        return _op("op_power_bps_if_target_bloodline", timing, target, rate, 1, 10000)
    if buff_id == 20630200 and tuple(params) == (0, 0, 0, (20010856, 20960020), 2, 0, 0, 1, 0, 2, 10000):
        return _op("op_power_bps_if_target_bloodline", timing, target, rate, 2, 10000)
    if buff_id == 20630180 and tuple(params) == (0, 0, 0, 20010855, 2, 0, 0, 1, 0, 2, -10000):
        return _op("op_power_bps_if_target_bloodline", timing, target, rate, 3, 10000)
    return None


def _is_meteor_mark_power(params: tuple) -> bool:
    return (
        _common_power_tail(params, mode=2)
        and _param_int(params, 3) in _meteor_mark_refs()
        and _param_int(params, 6) in (0, 8)
        and _param_int(params, 10) > 0
    )


def _meteor_mark_refs() -> frozenset[int]:
    refs = _as_int_tuple(BATTLE_GLOBAL_LISTS.get("parallel_buff_list", ()))
    return frozenset(ref_id for ref_id in refs if _is_meteor_mark_ref(ref_id))


def _is_meteor_mark_ref(buff_id: int) -> bool:
    return int(BUFF_KIND.get(buff_id, 0) or 0) == 4 and any(
        order == _BFT_NINETY_FOUR
        for _base_id, order, _params in _base_rows(buff_id)
    )


def _all_mark_refs(refs: tuple[int, ...]) -> bool:
    return all(int(BUFF_KIND.get(ref_id, 0) or 0) == 4 for ref_id in refs)


def _is_zero_delta_sentinel(buff_id: int) -> bool:
    rows = _base_rows(buff_id)
    if len(rows) != 1 or rows[0][1] != _BFT_ATTR_CHANGE:
        return False
    params = rows[0][2]
    return len(params) >= 3 and _all_zero(params[1:])
