"""Pak-axis family decoders.

Each decoder keys on a pak schema axis (currently
``EFFECT_CONF.effect_order``; ``BUFFBASE_CONF.buffbase_order`` arrives
in Phase 7C) rather than a hand-curated effect_id list.  Family axes
are the source of truth: pak's own schema field tells us which kernel
op to emit, so we don't need to maintain N hand-written rule rows for
N effect_ids that all share one axis value.

Public entry point: :func:`decode_family_axes`.  Returns the same
shape as :func:`decode_exact` —
``EmitOutcome | (EmitOutcome, timing_override) | None`` — so the
orchestrator in :mod:`roco.compiler_v2.effect_codegen` can chain the two
loaders with no special-case handling: family axes win first
(pak-native), then hand-curated overrides, then structural fallback.

Adding a new family axis: append a branch in
:func:`decode_family_axes` that reads the corresponding pak field and
delegates to a small private helper.  Keep the helpers pak-only —
they must not consult rule JSONL files or the kernel.
"""

from __future__ import annotations

from roco.generated.handler_indices import (
    H_BURN,
    H_DISPEL_DEBUFFS,
    H_DISPEL_MARKS,
    H_DISPEL_MARKS_TO_BURN,
    H_EXCHANGE_HP_RATIO,
    H_EXCHANGE_MOVES,
    H_HEAL_ENERGY,
    H_HEAL_HP,
    H_HIT_COUNT_DELTA,
    H_INSTALL_COUNTER,
    H_LIFE_DRAIN,
    H_MIRROR_ENEMY_BUFFS,
    H_PRIORITY_NEXT_DELTA,
    H_SET_SELF_COOLDOWN,
    H_SELF_BUFF,
    H_TRANSFER_MODS,
)
from roco.generated.static.pak_axes import BUFF_BASE_TO_ORDER

from roco.compiler_v2.effect_codegen.outcomes import EmitOutcome
from roco.compiler_v2.effect_codegen.params import extract_int_list, safe_int


# Pak ``effect_order`` values handled by this module.  One enum-ish
# value per family axis; keep names mirrored from Lua's
# ``Enum.EffectType`` where applicable so a reader can cross-reference
# pak's own naming.
ET_PURIFY = 4
ET_HEAL_HP = 5
ET_LIFE_DRAIN = 11
ET_HEAL_ENERGY = 19
ET_COUNTER = 31  # SkillPerformAutoBattleUtils.lua:189 (`EffectConf.effect_order == ET_COUNTER`)
ET_HIT_COUNT = 32
ET_SET_COOLDOWN = 37
ET_BUFF_CONVERT = 42
ET_EXCHANGE_RATIO_OR_STATE = 44
ET_EXCHANGE_SKILLS = 47
ET_COPY_BUFF = 50
ET_PRIORITY_NEXT = 51

# Counter-trigger install must always run AFTER_MOVE so the kernel can
# fold ``actor_counter_install_skill_id`` into ``SideState.counter_skill_id``
# in time for the next incoming hit.  Pak skill_result entries sometimes
# carry ``cast_moment`` other than 11 (observed: 6, 7, 12) — the override
# normalises the install window so the counter is always armed at the
# correct stage regardless of how the calling skill schedules it.
COUNTER_INSTALL_TIMING = 11


def decode_family_axes(
    effect_id: int,
    effect_conf: dict[int, dict],
    buff_conf: dict[int, dict],
) -> EmitOutcome | tuple[EmitOutcome, int] | None:
    """Return a pak-family outcome for ``effect_id``, or ``None`` to fall through.

    ``buff_conf`` is unused by the current axes but accepted so 7C
    buffbase_order decoders can plug in without changing the call sites.
    """
    rec = effect_conf.get(effect_id)
    if rec is None:
        return None
    order = int(rec.get("effect_order", 0))
    effect_type = int(rec.get("type", 0) or 0)
    if order == ET_PURIFY and effect_type == 1:
        return _decode_purify(rec)
    if order == ET_HEAL_HP and effect_type == 1:
        return _emit_from_param(rec, H_HEAL_HP, 1)
    if order == ET_LIFE_DRAIN and effect_type == 1:
        return _emit_from_param(rec, H_LIFE_DRAIN, 0)
    if order == ET_HEAL_ENERGY and effect_type == 3:
        return _emit_from_param(rec, H_HEAL_ENERGY, 0)
    if order == ET_COUNTER:
        return _decode_counter_install(rec)
    if order == ET_HIT_COUNT and effect_type == 1:
        return _decode_hit_count_delta(rec)
    if order == ET_SET_COOLDOWN and effect_type == 3:
        return _decode_self_cooldown(rec)
    if order == ET_BUFF_CONVERT and effect_type == 1:
        return _decode_buff_convert(rec, buff_conf)
    if order == ET_EXCHANGE_RATIO_OR_STATE and effect_type == 3:
        return _decode_exchange_ratio_or_state(rec)
    if order == ET_EXCHANGE_SKILLS and effect_type == 3:
        return _decode_exchange_skills(rec)
    if order == ET_COPY_BUFF and effect_type == 1:
        return _decode_copy_buff(rec)
    if order == ET_PRIORITY_NEXT and effect_type == 1:
        return _decode_priority_next(rec)
    return None


def _params(rec: dict) -> list:
    return rec.get("effect_param") or rec.get("params") or []


def _emit(handler_idx: int, p0: int, p1: int = 0, p2: int = 0, p3: int = 0) -> EmitOutcome:
    return EmitOutcome(handler_idx, p0, p1, p2, p3, 1)


def _emit_from_param(rec: dict, handler_idx: int, slot: int) -> EmitOutcome | None:
    params_raw = _params(rec)
    value = safe_int(params_raw, slot)
    if value == 0:
        return None
    return _emit(handler_idx, value)


def _decode_purify(rec: dict) -> EmitOutcome | None:
    """Decode pak's generic full-debuff cleanse shape.

    ET_PURIFY has many selective dispel variants.  The engine currently
    implements only the full debuff clear: ``effect_param`` slot vector
    ``[1], [2], [99], [99], [0]``.  This is the pak param shape used by
    both visible and no-float-text versions, so future ids with the same
    shape route without adding a semantic row.
    """
    params_raw = _params(rec)
    if (
        safe_int(params_raw, 0) == 1
        and safe_int(params_raw, 1) == 2
        and safe_int(params_raw, 2) == 99
        and safe_int(params_raw, 3) == 99
        and safe_int(params_raw, 4) == 0
    ):
        return _emit(H_DISPEL_DEBUFFS, 0)
    return None


def _decode_counter_install(rec: dict) -> tuple[EmitOutcome, int] | None:
    """Build an ``H_INSTALL_COUNTER`` emit from a pak ``effect_order=31`` row.

    ``effect_param[0].params[0]`` is the 70xxxxx response skill_id that
    fires on the next incoming hit.  Returns ``None`` when the slot is
    empty or out of the response-skill id range — those records will
    surface as gaps downstream rather than installing a bogus counter.
    """
    params_raw = _params(rec)
    response_skill_id = safe_int(params_raw, 0)
    if not (7000000 <= response_skill_id < 8000000):
        return None
    outcome = EmitOutcome(
        handler_idx=H_INSTALL_COUNTER,
        p0=response_skill_id,
        p1=0,
        p2=0,
        p3=0,
        stacks=1,
    )
    return outcome, COUNTER_INSTALL_TIMING


def _decode_buff_convert(rec: dict, buff_conf: dict[int, dict]) -> EmitOutcome | None:
    """Decode supported ET_BUFF_CONVERT mark transforms from pak shape."""
    params_raw = _params(rec)
    source_ids = extract_int_list(params_raw, 1)
    target_ids = extract_int_list(params_raw, 2)
    if safe_int(params_raw, 0) != 0 or safe_int(params_raw, 3) != 99 or safe_int(params_raw, 4) != 0:
        return None

    if (
        source_ids
        and _all_regular_marks(source_ids, buff_conf)
        and len(target_ids) == 1
        and _is_internal_mark_sentinel(target_ids[0], buff_conf)
    ):
        return _emit(H_DISPEL_MARKS, 0)

    if (
        len(source_ids) == 1
        and _is_internal_mark_sentinel(source_ids[0], buff_conf)
        and target_ids
        and len(set(target_ids)) == 1
        and _buff_handler_family(target_ids[0], buff_conf) == H_BURN
    ):
        return _emit(H_DISPEL_MARKS_TO_BURN, len(target_ids))
    return None


def _decode_copy_buff(rec: dict) -> EmitOutcome | None:
    """Decode pak's enemy-positive-buff mirror shape."""
    params_raw = _params(rec)
    if (
        safe_int(params_raw, 0) == 0
        and safe_int(params_raw, 1) == 1
        and safe_int(params_raw, 2) == 0
        and not extract_int_list(params_raw, 3)
        and safe_int(params_raw, 4) == 99
        and safe_int(params_raw, 5) == 1
        and safe_int(params_raw, 6) == 1
    ):
        return _emit(H_MIRROR_ENEMY_BUFFS, 0)
    return None


def _decode_hit_count_delta(rec: dict) -> EmitOutcome | None:
    params_raw = _params(rec)
    delta = safe_int(params_raw, 0)
    if delta <= 0 or safe_int(params_raw, 1) != 0 or safe_int(params_raw, 2) != 0:
        return None
    return _emit(H_HIT_COUNT_DELTA, delta)


def _decode_self_cooldown(rec: dict) -> EmitOutcome | None:
    params_raw = _params(rec)
    turns = safe_int(params_raw, 0)
    if turns <= 0 or safe_int(params_raw, 2) != 1 or safe_int(params_raw, 3) != 0:
        return None
    return _emit(H_SET_SELF_COOLDOWN, turns)


def _decode_priority_next(rec: dict) -> EmitOutcome | None:
    params_raw = _params(rec)
    delta = safe_int(params_raw, 2)
    if delta == 0:
        return None
    return _emit(H_PRIORITY_NEXT_DELTA, delta)


def _decode_exchange_ratio_or_state(rec: dict) -> EmitOutcome | None:
    mode = safe_int(_params(rec), 0)
    if mode == 1:
        return _emit(H_EXCHANGE_HP_RATIO, 0)
    if mode == 3:
        return _emit(H_TRANSFER_MODS, 0)
    return None


def _decode_exchange_skills(rec: dict) -> EmitOutcome | None:
    mode = safe_int(_params(rec), 0)
    if mode == 1:
        return _emit(H_EXCHANGE_MOVES, 0)
    return None


def _all_regular_marks(buff_ids: list[int], buff_conf: dict[int, dict]) -> bool:
    for buff_id in buff_ids:
        rec = buff_conf.get(buff_id)
        if rec is None or int(rec.get("type", 0) or 0) != 4:
            return False
    return True


def _is_internal_mark_sentinel(buff_id: int, buff_conf: dict[int, dict]) -> bool:
    rec = buff_conf.get(buff_id)
    if rec is None:
        return False
    name = str(rec.get("editor_name") or rec.get("name") or "")
    if "标记" in name and _buff_handler_family(buff_id, buff_conf) == H_SELF_BUFF:
        return True
    if name:
        return False
    if int(rec.get("type", 0) or 0) != 3 or int(rec.get("add_max", 0) or 0) != 99:
        return False
    if _buff_handler_family(buff_id, buff_conf) != H_SELF_BUFF:
        return False
    for reduce_rule in rec.get("buff_group_reduce") or []:
        if not isinstance(reduce_rule, dict):
            continue
        if int(reduce_rule.get("reduce_type") or 0) != 13:
            continue
        params = reduce_rule.get("reduce_param") or []
        if len(params) >= 2 and int(params[1] or 0) == 99:
            return True
    return False


def _buff_handler_family(buff_id: int, buff_conf: dict[int, dict]) -> int:
    rec = buff_conf.get(buff_id)
    if rec is None:
        return 0
    for base_id in rec.get("buff_base_ids") or []:
        order = BUFF_BASE_TO_ORDER.get(int(base_id), 0)
        if order == 7:
            return H_BURN
        if order == 1:
            return H_SELF_BUFF
    return 0
