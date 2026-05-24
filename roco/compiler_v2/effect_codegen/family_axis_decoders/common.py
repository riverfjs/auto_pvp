"""Shared helpers for pak family-axis decoders."""

from __future__ import annotations

from functools import lru_cache

from roco.compiler_v2.effect_codegen.outcomes import EmitOutcome
from roco.compiler_v2.effect_codegen.params import safe_int
from roco.compiler_v2.sources import LuaEnumSource
from roco.engine.kernel.op_rows import TIMING_AFTER_MOVE, TIMING_SWITCH_IN


def _effect_type(name: str) -> int:
    return int(_effect_type_enum()[name])


@lru_cache(maxsize=1)
def _effect_type_enum() -> dict[str, int]:
    return LuaEnumSource().enums(("EffectType",))["EffectType"]


ET_PURIFY = _effect_type("ET_PURIFY")
ET_HEAL_HP = _effect_type("ET_RECOVER")
ET_LIFE_DRAIN = _effect_type("ET_SUCKBLOOD")
ET_HEAL_ENERGY = _effect_type("ET_CHANGE_ENERGY")
ET_BUFF_BY_PACK_PET_NUM = _effect_type("ET_BUFF_BY_PACK_PET_NUM")
ET_COUNTER = _effect_type("ET_COUNTER")
ET_HIT_COUNT = _effect_type("ET_MULTIPLE")
ET_HERO = _effect_type("ET_HERO")
ET_SET_COOLDOWN = _effect_type("ET_SKILL_CD")
ET_BUFF_CONVERT = _effect_type("ET_BUFF_CONVERT")
ET_EXCHANGE_RATIO_OR_STATE = _effect_type("ET_SWAP_STAT")
ET_EXCHANGE_SKILLS = _effect_type("ET_SWAP_SKILLS")
ET_COPY_BUFF = _effect_type("ET_COPY_BUFF")
ET_PRIORITY_NEXT = _effect_type("ET_FAST_SKILL")
ET_BUFF_BY_CHANGE_TIMES = _effect_type("ET_BUFF_BY_CHANGE_TIMES")
ET_BUFF_BY_EQUIP_SKILL_NUM = _effect_type("ET_BUFF_BY_EQUIP_SKILL_NUM")
ET_LIMIT_FIGHT_BY_HP = _effect_type("ET_LIMIT_FIGHT_BY_HP")

COUNTER_INSTALL_TIMING = TIMING_AFTER_MOVE
SWITCH_IN_TIMING = TIMING_SWITCH_IN
COUNT_FAINTED_ALLY = -1


def params(rec: dict) -> list:
    return rec.get("effect_param") or rec.get("params") or []


def emit(handler_idx: int, p0: int, p1: int = 0, p2: int = 0, p3: int = 0) -> EmitOutcome:
    return EmitOutcome(handler_idx, p0, p1, p2, p3, 1)


def emit_from_param(rec: dict, handler_idx: int, slot: int) -> EmitOutcome | None:
    params_raw = params(rec)
    value = safe_int(params_raw, slot)
    if value == 0:
        return None
    return emit(handler_idx, value)
