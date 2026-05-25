"""Pak BFT_ASSIGN expansion helpers.

``BFT_ASSIGN`` is a pak structural dispatcher: the BUFFBASE row points at
one or more effect/buff refs, optionally overriding target and success rate.
It is not a runtime primitive family by itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Callable

from roco.compiler_v2.effect_codegen.buffbase_source import (
    BUFFBASE_ORDER,
    BUFFBASE_PARAMS,
)
from roco.compiler_v2.effect_codegen.outcomes import GapOutcome
from roco.compiler_v2.sources import LuaEnumSource


@lru_cache(maxsize=1)
def _buff_type_enum() -> dict[str, int]:
    return LuaEnumSource().enums(("BuffType",))["BuffType"]


def _buff_type(name: str) -> int:
    return int(_buff_type_enum()[name])


BFT_ASSIGN_ORDER = _buff_type("BFT_ASSIGN")


@dataclass(frozen=True)
class AssignRef:
    ref_id: int
    target_type: int | None
    success_rate: int
    source_buff_id: int
    source_base_id: int


def as_int_tuple(value: object) -> tuple[int, ...]:
    if isinstance(value, tuple):
        raw_values = value
    elif isinstance(value, list):
        raw_values = tuple(value)
    elif value is None:
        raw_values = ()
    else:
        raw_values = (value,)
    out: list[int] = []
    for raw in raw_values:
        try:
            item = int(raw)
        except (TypeError, ValueError):
            continue
        if item:
            out.append(item)
    return tuple(out)


def assign_refs(
    buff_id: int,
    buff_conf: dict[int, dict],
) -> tuple[list[AssignRef], list[GapOutcome]] | None:
    rec = buff_conf.get(buff_id)
    if rec is None:
        return None
    base_ids = [int(v) for v in rec.get("buff_base_ids") or () if v]
    assign_base_ids = [
        base_id for base_id in base_ids
        if BUFFBASE_ORDER.get(base_id) == BFT_ASSIGN_ORDER
    ]
    if not assign_base_ids:
        return None
    refs: list[AssignRef] = []
    gaps: list[GapOutcome] = []
    for base_id in assign_base_ids:
        params = BUFFBASE_PARAMS.get(base_id) or ()
        raw_refs = as_int_tuple(params[0] if len(params) > 0 else ())
        rate = (
            int(params[1])
            if len(params) > 1 and not isinstance(params[1], tuple)
            else 10000
        )
        target_code = (
            int(params[2])
            if len(params) > 2 and not isinstance(params[2], tuple)
            else 0
        )
        if not raw_refs:
            gaps.append(GapOutcome(
                primitive=f"assign_{base_id}",
                effect_id=None,
                buff_id=buff_id,
                reason="assign_no_refs",
                params={"buff_id": buff_id, "buff_base_id": base_id},
            ))
            continue
        if rate <= 0:
            gaps.append(GapOutcome(
                primitive=f"assign_{base_id}",
                effect_id=None,
                buff_id=buff_id,
                reason="assign_zero_rate",
                params={"buff_id": buff_id, "buff_base_id": base_id, "rate": rate},
            ))
            continue
        if target_code not in (0, 1, 2, 3, 4):
            gaps.append(GapOutcome(
                primitive=f"assign_condition_{target_code}",
                effect_id=None,
                buff_id=buff_id,
                reason="assign_condition_unsupported",
                params={
                    "buff_id": buff_id,
                    "buff_base_id": base_id,
                    "assigned_refs": list(raw_refs),
                    "assign_target_or_condition": target_code,
                },
            ))
            continue
        for ref_id in raw_refs:
            refs.append(AssignRef(
                ref_id=ref_id,
                target_type=target_code or None,
                success_rate=rate,
                source_buff_id=buff_id,
                source_base_id=base_id,
            ))
    return refs, gaps


def single_assign_buff_from_effect(
    effect_id: int,
    effect_conf: dict[int, dict],
    buff_conf: dict[int, dict],
    collect_buff_candidates: Callable[[list, dict[int, dict]], list[int]],
) -> int:
    rec = effect_conf.get(effect_id)
    if rec is None or int(rec.get("type", 0) or 0) != 1:
        return 0
    params_raw = rec.get("effect_param") or rec.get("params") or []
    candidates = collect_buff_candidates(params_raw, buff_conf)
    if len(candidates) != 1:
        return 0
    buff_id = candidates[0]
    return buff_id if assign_refs(buff_id, buff_conf) is not None else 0
