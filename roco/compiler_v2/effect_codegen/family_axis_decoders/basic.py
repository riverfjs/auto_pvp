"""Scalar and simple pak effect-order decoders."""

from __future__ import annotations

from roco.compiler_v2.effect_codegen.outcomes import EmitOutcome
from roco.compiler_v2.effect_codegen.params import extract_int_list, safe_int

from roco.compiler_v2.effect_codegen.family_axis_decoders.common import (
    COUNTER_INSTALL_TIMING,
    emit_effect_order,
    emit_effect_order_variant,
    params,
)


def decode_heal_energy(rec: dict) -> EmitOutcome | None:
    params_raw = params(rec)
    direct = safe_int(params_raw, 0)
    if direct != 0:
        return emit_effect_order("ET_CHANGE_ENERGY", direct)
    base = safe_int(params_raw, 1)
    ratio = safe_int(params_raw, 2)
    if base == 0 and ratio == 0 and len(params_raw) >= 3:
        return emit_effect_order("ET_CHANGE_ENERGY", 0)
    if base <= 0 or ratio == 0:
        return None
    amount = base * ratio // 10000
    if amount == 0:
        return None
    return emit_effect_order("ET_CHANGE_ENERGY", amount)


def decode_purify(rec: dict) -> EmitOutcome | None:
    params_raw = params(rec)
    if (
        safe_int(params_raw, 0) == 1
        and safe_int(params_raw, 1) == 2
        and safe_int(params_raw, 2) == 99
        and safe_int(params_raw, 3) == 99
        and safe_int(params_raw, 4) == 0
    ):
        return emit_effect_order("ET_PURIFY", 0)
    return None


def decode_counter_install(rec: dict) -> tuple[EmitOutcome, str] | None:
    response_skill_id = safe_int(params(rec), 0)
    if not (7000000 <= response_skill_id < 8000000):
        return None
    return emit_effect_order("ET_COUNTER", response_skill_id), COUNTER_INSTALL_TIMING


def decode_hit_count_delta(rec: dict) -> EmitOutcome | None:
    params_raw = params(rec)
    delta = safe_int(params_raw, 0)
    if delta > 0 and safe_int(params_raw, 1) == 0 and safe_int(params_raw, 2) == 0:
        return emit_effect_order("ET_MULTIPLE", delta)
    per_same_skill = safe_int(params_raw, 1)
    skill_id = safe_int(params_raw, 2)
    if delta == -1 and per_same_skill > 0 and skill_id >= 100000:
        return emit_effect_order_variant(
            "ET_MULTIPLE",
            "team_skill_count",
            per_same_skill,
            skill_id,
        )
    return None


def decode_self_cooldown(rec: dict) -> EmitOutcome | None:
    params_raw = params(rec)
    turns = safe_int(params_raw, 0)
    if turns <= 0 or safe_int(params_raw, 2) != 1 or safe_int(params_raw, 3) != 0:
        return None
    return emit_effect_order("ET_SKILL_CD", turns)


def decode_priority_next(rec: dict) -> EmitOutcome | None:
    delta = safe_int(params(rec), 2)
    if delta == 0:
        return None
    return emit_effect_order("ET_FAST_SKILL", delta)


def decode_exchange_ratio_or_state(rec: dict) -> EmitOutcome | None:
    mode = safe_int(params(rec), 0)
    if mode == 1:
        return emit_effect_order_variant("ET_SWAP_STAT", "hp_ratio", 0)
    if mode == 3:
        return emit_effect_order_variant("ET_SWAP_STAT", "transfer_mods", 0)
    return None


def decode_exchange_skills(rec: dict) -> EmitOutcome | None:
    if safe_int(params(rec), 0) == 1:
        return emit_effect_order("ET_SWAP_SKILLS", 0)
    return None


def decode_copy_buff(rec: dict) -> EmitOutcome | None:
    params_raw = params(rec)
    if (
        safe_int(params_raw, 0) == 0
        and safe_int(params_raw, 1) == 1
        and safe_int(params_raw, 2) == 0
        and not extract_int_list(params_raw, 3)
        and safe_int(params_raw, 4) == 99
        and safe_int(params_raw, 5) == 1
        and safe_int(params_raw, 6) == 1
    ):
        return emit_effect_order("ET_COPY_BUFF", 0)
    return None
