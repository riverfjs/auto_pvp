"""Hit-count BUFF_CONF pak shape matchers."""

from __future__ import annotations

from roco.engine.artifacts.linked_op import LinkedOp
from roco.engine.artifacts.pak_ref_common import (
    BUFF_BASE_IDS,
    BUFFBASE_ORDER,
    _all_zero,
    _as_int_tuple,
    _base_rows,
    _condition_refs_are_cute_effects,
    _condition_refs_are_poison_effects,
    _conditional_refs_and_grants,
    _grant_refs_are_hit_count_effects,
    _op,
    _single_int,
    buff_type,
)
from roco.engine.kernel.core.rows import TIMING_HOOK_BEFORE_MOVE


def link_team_skill_hit_count_buff(
    buff_id: int,
    timing: int,
    target: int,
    rate: int,
    stack_count: int,
    *,
    source_name: str,
) -> LinkedOp | None:
    rows = _base_rows(buff_id)
    if len(rows) != 1 or rows[0][1] != buff_type("BFT_IMMUNE"):
        return None
    params = rows[0][2]
    if len(params) < 2 or _as_int_tuple(params[0]) != (3,):
        return None
    skill_ids = tuple(v for v in _as_int_tuple(params[1]) if v > 0)
    if len(skill_ids) > 1:
        return None
    skill_id = skill_ids[0] if skill_ids else 0
    return _op("op_hit_count_by_team_skill_count", timing, target, rate, stack_count, skill_id)


def link_hit_count_delta_buff(
    buff_id: int,
    timing: int,
    target: int,
    rate: int,
    stack_count: int,
    *,
    source_name: str,
) -> LinkedOp | None:
    rows = _base_rows(buff_id)
    if len(rows) != 1 or rows[0][1] != buff_type("BFT_MULTIPLE_NUM"):
        return None
    params = rows[0][2]
    if len(params) < 3:
        return None
    amount = _single_int(params[0])
    mode = _single_int(params[2])
    if amount is None or amount == 0:
        return None
    if mode == 0:
        skill_ids = tuple(v for v in _as_int_tuple(params[1]) if v > 0)
        if len(skill_ids) > 3:
            return None
        padded = (skill_ids + (0, 0, 0))[:3]
        return _op("op_hit_count_delta", timing, target, rate, amount * stack_count, padded[0], padded[1], padded[2])
    if mode == 1:
        return _op("op_hit_count_percent_delta", timing, target, rate, amount)
    return None


def link_conditional_hit_count_buff(
    buff_id: int,
    timing: int,
    target: int,
    rate: int,
    amount: int,
    *,
    source_name: str,
) -> LinkedOp | None:
    base_ids = BUFF_BASE_IDS.get(buff_id) or ()
    if not base_ids or any(BUFFBASE_ORDER.get(base_id) != buff_type("BFT_NINETY_ONE") for base_id in base_ids):
        return None
    if amount <= 0:
        return None
    condition_refs, grant_refs = _conditional_refs_and_grants(base_ids)
    if not _grant_refs_are_hit_count_effects(grant_refs):
        return None
    if _condition_refs_are_poison_effects(condition_refs):
        return _op("op_hit_count_per_poison_effect", TIMING_HOOK_BEFORE_MOVE, target, rate, amount)
    if _condition_refs_are_cute_effects(condition_refs):
        return _op("op_cute_hit_per_stack", TIMING_HOOK_BEFORE_MOVE, target, rate, amount)
    return None


def sum_hit_count_delta_amount(buff_ids: tuple[int, ...]) -> int:
    if not buff_ids:
        return 0
    total = 0
    for buff_id in buff_ids:
        amount = hit_count_delta_amount(buff_id)
        if amount <= 0:
            return 0
        total += amount
    return total


def hit_count_delta_amount(buff_id: int) -> int:
    rows = _base_rows(buff_id)
    if len(rows) != 1 or rows[0][1] != buff_type("BFT_MULTIPLE_NUM"):
        return 0
    params = rows[0][2]
    if len(params) < 4:
        return 0
    amount = _single_int(params[0])
    if amount is None or amount <= 0:
        return 0
    if not _all_zero(params[1:]):
        return 0
    return amount
