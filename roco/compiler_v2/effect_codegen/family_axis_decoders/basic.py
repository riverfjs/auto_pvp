"""Scalar and simple pak effect-order decoders."""

from __future__ import annotations

from roco.compiler_v2.effect_codegen.outcomes import EmitOutcome
from roco.compiler_v2.effect_codegen.params import extract_int_list, safe_int
from roco.compiler_v2.handler_registry import (
    H_DISPEL_DEBUFFS,
    H_EXCHANGE_HP_RATIO,
    H_EXCHANGE_MOVES,
    H_HEAL_ENERGY,
    H_HIT_COUNT_DELTA,
    H_INSTALL_COUNTER,
    H_MIRROR_ENEMY_BUFFS,
    H_PRIORITY_NEXT_DELTA,
    H_SET_SELF_COOLDOWN,
    H_TRANSFER_MODS,
)

from roco.compiler_v2.effect_codegen.family_axis_decoders.common import (
    COUNTER_INSTALL_TIMING,
    emit,
    params,
)


def decode_heal_energy(rec: dict) -> EmitOutcome | None:
    params_raw = params(rec)
    direct = safe_int(params_raw, 0)
    if direct != 0:
        return emit(H_HEAL_ENERGY, direct)
    base = safe_int(params_raw, 1)
    ratio = safe_int(params_raw, 2)
    if base == 0 and ratio == 0 and len(params_raw) >= 3:
        return emit(H_HEAL_ENERGY, 0)
    if base <= 0 or ratio == 0:
        return None
    amount = base * ratio // 10000
    if amount == 0:
        return None
    return emit(H_HEAL_ENERGY, amount)


def decode_purify(rec: dict) -> EmitOutcome | None:
    params_raw = params(rec)
    if (
        safe_int(params_raw, 0) == 1
        and safe_int(params_raw, 1) == 2
        and safe_int(params_raw, 2) == 99
        and safe_int(params_raw, 3) == 99
        and safe_int(params_raw, 4) == 0
    ):
        return emit(H_DISPEL_DEBUFFS, 0)
    return None


def decode_counter_install(rec: dict) -> tuple[EmitOutcome, int] | None:
    response_skill_id = safe_int(params(rec), 0)
    if not (7000000 <= response_skill_id < 8000000):
        return None
    return emit(H_INSTALL_COUNTER, response_skill_id), COUNTER_INSTALL_TIMING


def decode_hit_count_delta(rec: dict) -> EmitOutcome | None:
    params_raw = params(rec)
    delta = safe_int(params_raw, 0)
    if delta <= 0 or safe_int(params_raw, 1) != 0 or safe_int(params_raw, 2) != 0:
        return None
    return emit(H_HIT_COUNT_DELTA, delta)


def decode_self_cooldown(rec: dict) -> EmitOutcome | None:
    params_raw = params(rec)
    turns = safe_int(params_raw, 0)
    if turns <= 0 or safe_int(params_raw, 2) != 1 or safe_int(params_raw, 3) != 0:
        return None
    return emit(H_SET_SELF_COOLDOWN, turns)


def decode_priority_next(rec: dict) -> EmitOutcome | None:
    delta = safe_int(params(rec), 2)
    if delta == 0:
        return None
    return emit(H_PRIORITY_NEXT_DELTA, delta)


def decode_exchange_ratio_or_state(rec: dict) -> EmitOutcome | None:
    mode = safe_int(params(rec), 0)
    if mode == 1:
        return emit(H_EXCHANGE_HP_RATIO, 0)
    if mode == 3:
        return emit(H_TRANSFER_MODS, 0)
    return None


def decode_exchange_skills(rec: dict) -> EmitOutcome | None:
    if safe_int(params(rec), 0) == 1:
        return emit(H_EXCHANGE_MOVES, 0)
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
        return emit(H_MIRROR_ENEMY_BUFFS, 0)
    return None
