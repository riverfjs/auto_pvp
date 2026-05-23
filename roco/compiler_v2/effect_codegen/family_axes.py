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
    H_ENTRY_BUFF_PER_SKILL_COUNT,
    H_ENTRY_ELEMENT_SKILL_MOD_BY_COUNT,
    H_HEAL_ENERGY,
    H_HEAL_HP,
    H_HIT_COUNT_DELTA,
    H_INSTALL_COUNTER,
    H_ENTRY_SELF_BUFF_BY_SIDE_COUNT,
    H_ENTRY_SELF_BUFF_BY_SOURCE_COUNT,
    H_ENTRY_SELF_BUFF_IF_ENERGY,
    H_ENTRY_SELF_BUFF_BY_USED_SKILL_COUNT,
    H_LIFE_DRAIN,
    H_MIRROR_ENEMY_BUFFS,
    H_PRIORITY_NEXT_DELTA,
    H_SET_SELF_COOLDOWN,
    H_SELF_BUFF,
    H_TRANSFER_MODS,
)
from roco.common.buffbase import pack_buff_delta_from_buff_ids
from roco.common.entry_sources import (
    ENTRY_SOURCE_COUNTER,
    ENTRY_SOURCE_DEFENSE,
    ENTRY_SOURCE_ENEMY_SKILL_DAM_TYPE,
    ENTRY_SOURCE_ENEMY_SWITCH,
    ENTRY_SOURCE_EQUIPPED_ELEMENT,
    ENTRY_SOURCE_STATUS,
    ENTRY_SOURCE_USED_ELEMENT,
    entry_source_code,
)
from roco.generated.buffbase_params import BUFFBASE_ORDER, BUFFBASE_PARAMS
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
ET_BUFF_BY_PACK_PET_NUM = 22
ET_COUNTER = 31  # SkillPerformAutoBattleUtils.lua:189 (`EffectConf.effect_order == ET_COUNTER`)
ET_HIT_COUNT = 32
ET_HERO = 34
ET_SET_COOLDOWN = 37
ET_BUFF_CONVERT = 42
ET_EXCHANGE_RATIO_OR_STATE = 44
ET_EXCHANGE_SKILLS = 47
ET_COPY_BUFF = 50
ET_PRIORITY_NEXT = 51
ET_BUFF_BY_CHANGE_TIMES = 61
ET_BUFF_BY_EQUIP_SKILL_NUM = 64
ET_LIMIT_FIGHT_BY_HP = 77

# Counter-trigger install must always run AFTER_MOVE so the kernel can
# fold ``actor_counter_install_skill_id`` into ``SideState.counter_skill_id``
# in time for the next incoming hit.  Pak skill_result entries sometimes
# carry ``cast_moment`` other than 11 (observed: 6, 7, 12) — the override
# normalises the install window so the counter is always armed at the
# correct stage regardless of how the calling skill schedules it.
COUNTER_INSTALL_TIMING = 11
SWITCH_IN_TIMING = 24
COUNT_FAINTED_ALLY = -1
MODE_POWER_BPS = 1
MODE_POWER_FLAT = 2
MODE_COST_REDUCE = 3
MODE_POISON_STACKS = 4


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
        return _decode_heal_energy(rec)
    if order == ET_BUFF_BY_PACK_PET_NUM and effect_type == 3:
        return _decode_buff_by_pack_pet_num(rec, buff_conf)
    if order == ET_COUNTER:
        return _decode_counter_install(rec)
    if order == ET_HERO and effect_type == 3:
        return _decode_hero_entry(rec, buff_conf)
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
    if order == ET_BUFF_BY_CHANGE_TIMES and effect_type == 3:
        return _decode_entry_static_buff(rec, buff_conf)
    if order == ET_BUFF_BY_EQUIP_SKILL_NUM and effect_type == 3:
        return _decode_buff_by_equip_skill_num(rec, buff_conf)
    if order == ET_LIMIT_FIGHT_BY_HP and effect_type == 3:
        return _decode_entry_buff_if_energy(rec, buff_conf)
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


def _decode_heal_energy(rec: dict) -> EmitOutcome | None:
    params_raw = _params(rec)
    direct = safe_int(params_raw, 0)
    if direct != 0:
        return _emit(H_HEAL_ENERGY, direct)
    base = safe_int(params_raw, 1)
    ratio = safe_int(params_raw, 2)
    if base <= 0 or ratio == 0:
        return None
    amount = base * ratio // 10000
    if amount == 0:
        return None
    return _emit(H_HEAL_ENERGY, amount)


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


def _decode_buff_by_pack_pet_num(rec: dict, buff_conf: dict[int, dict]) -> tuple[EmitOutcome, int] | None:
    params_raw = _params(rec)
    buff_ids = extract_int_list(params_raw, 3)
    packed = pack_buff_delta_from_buff_ids(buff_ids, buff_conf)
    if packed == 0:
        return None
    fainted_mode = safe_int(params_raw, 1)
    if fainted_mode == 2:
        return _emit(H_ENTRY_SELF_BUFF_BY_SIDE_COUNT, COUNT_FAINTED_ALLY, packed), SWITCH_IN_TIMING
    element = safe_int(params_raw, 0, -1)
    if element >= 0:
        return _emit(H_ENTRY_SELF_BUFF_BY_SIDE_COUNT, element, packed), SWITCH_IN_TIMING
    return None


def _decode_entry_static_buff(rec: dict, buff_conf: dict[int, dict]) -> tuple[EmitOutcome, int] | None:
    packed = pack_buff_delta_from_buff_ids(extract_int_list(_params(rec), 0), buff_conf)
    if packed == 0:
        return None
    return _emit(H_SELF_BUFF, packed), SWITCH_IN_TIMING


def _decode_entry_buff_if_energy(rec: dict, buff_conf: dict[int, dict]) -> tuple[EmitOutcome, int] | None:
    params_raw = _params(rec)
    required = safe_int(params_raw, 1)
    selector = safe_int(params_raw, 2)
    if selector not in (1, 2):
        return None
    packed = pack_buff_delta_from_buff_ids(extract_int_list(params_raw, 3), buff_conf)
    if packed == 0:
        return None
    return _emit(H_ENTRY_SELF_BUFF_IF_ENERGY, selector, required, packed), SWITCH_IN_TIMING


def _decode_hero_entry(rec: dict, buff_conf: dict[int, dict]) -> tuple[EmitOutcome, int] | None:
    params_raw = _params(rec)
    event_count_buff = _decode_hero_event_count_buff(params_raw, buff_conf)
    if event_count_buff is not None:
        return event_count_buff
    if safe_int(params_raw, 3) != 1:
        return None
    skill_count_mod = _decode_entry_buff_per_used_skill_count(params_raw, buff_conf)
    if skill_count_mod is not None:
        return skill_count_mod
    source = _hero_count_source(params_raw)
    if source is not None:
        element_mod = _decode_entry_element_mod(
            _base_ids_from_buff_ids(extract_int_list(params_raw, 4), buff_conf),
            source,
        )
        if element_mod is not None:
            return element_mod
    packed = pack_buff_delta_from_buff_ids(extract_int_list(params_raw, 4), buff_conf)
    if packed == 0:
        return None
    element = safe_int(params_raw, 0, -1)
    if element > 0:
        return _emit(H_ENTRY_SELF_BUFF_BY_USED_SKILL_COUNT, element, packed), SWITCH_IN_TIMING
    return None


def _decode_hero_event_count_buff(
    params_raw: list,
    buff_conf: dict[int, dict],
) -> tuple[EmitOutcome, int] | None:
    if safe_int(params_raw, 3) != 2:
        return None
    packed = pack_buff_delta_from_buff_ids(extract_int_list(params_raw, 4), buff_conf)
    if packed == 0:
        return None
    skill_dam_type = safe_int(params_raw, 0)
    if skill_dam_type > 0:
        return _emit(
            H_ENTRY_SELF_BUFF_BY_SOURCE_COUNT,
            entry_source_code(ENTRY_SOURCE_ENEMY_SKILL_DAM_TYPE, skill_dam_type),
            packed,
        ), SWITCH_IN_TIMING
    if safe_int(params_raw, 7) == 3:
        return _emit(
            H_ENTRY_SELF_BUFF_BY_SOURCE_COUNT,
            entry_source_code(ENTRY_SOURCE_ENEMY_SWITCH),
            packed,
        ), SWITCH_IN_TIMING
    return None


def _decode_buff_by_equip_skill_num(
    rec: dict,
    buff_conf: dict[int, dict],
) -> tuple[EmitOutcome, int] | None:
    params_raw = _params(rec)
    source_element = safe_int(params_raw, 0, -1)
    if source_element <= 0:
        return None
    return _decode_entry_element_mod(
        _base_ids_from_buff_ids(extract_int_list(params_raw, 4), buff_conf),
        entry_source_code(ENTRY_SOURCE_EQUIPPED_ELEMENT, source_element),
    )


def _decode_entry_buff_per_used_skill_count(
    params_raw: list,
    buff_conf: dict[int, dict],
) -> tuple[EmitOutcome, int] | None:
    element = safe_int(params_raw, 0, -1)
    if element <= 0:
        return None
    base_ids = _base_ids_from_buff_ids(extract_int_list(params_raw, 4), buff_conf)
    if len(base_ids) != 1:
        return None
    base_id = base_ids[0]
    order = BUFFBASE_ORDER.get(base_id)
    base_params = BUFFBASE_PARAMS.get(base_id) or ()
    if order == 32 and len(base_params) >= 4:
        cost_delta = _param_int(base_params, 3)
        if cost_delta < 0:
            return _emit(H_ENTRY_BUFF_PER_SKILL_COUNT, element, 1, abs(cost_delta)), SWITCH_IN_TIMING
    if order == 23 and len(base_params) >= 6:
        affected = base_params[0]
        mode = _param_int(base_params, 4)
        amount = _param_int(base_params, 5)
        if affected == 0 and mode == 2 and amount > 0:
            return _emit(H_ENTRY_BUFF_PER_SKILL_COUNT, element, 2, amount), SWITCH_IN_TIMING
    return None


def _decode_entry_element_mod(
    base_ids: list[int],
    source_code: int,
) -> tuple[EmitOutcome, int] | None:
    parsed: list[tuple[int, int, int]] = []
    for base_id in base_ids:
        base_params = BUFFBASE_PARAMS.get(base_id) or ()
        order = BUFFBASE_ORDER.get(base_id)
        if order == 23 and len(base_params) >= 6:
            mask = _element_mask(base_params[0])
            mode = _param_int(base_params, 4)
            amount = _param_int(base_params, 5)
            if mask and mode in (MODE_POWER_BPS, MODE_POWER_FLAT) and amount > 0:
                parsed.append((mask, amount, mode))
        elif order == 32 and len(base_params) >= 4:
            mask = _element_mask(base_params[0])
            cost_delta = _param_int(base_params, 3)
            if mask and cost_delta < 0:
                parsed.append((mask, abs(cost_delta), MODE_COST_REDUCE))
        elif order == 35 and len(base_params) >= 5:
            mask = _element_mask(base_params[0])
            if mask:
                parsed.append((mask, 1, MODE_POISON_STACKS))
    if not parsed:
        return None
    modes = {mode for _mask, _amount, mode in parsed}
    amounts = {amount for _mask, amount, _mode in parsed}
    if len(modes) != 1 or len(amounts) != 1:
        return None
    mask = 0
    for item_mask, _amount, _mode in parsed:
        mask |= item_mask
    amount = parsed[0][1]
    mode = parsed[0][2]
    return _emit(H_ENTRY_ELEMENT_SKILL_MOD_BY_COUNT, source_code, mask, amount, mode), SWITCH_IN_TIMING


def _hero_count_source(params_raw: list) -> int | None:
    if safe_int(params_raw, 7) == 1:
        return entry_source_code(ENTRY_SOURCE_COUNTER)
    category = safe_int(params_raw, 2)
    if category == 2:
        return entry_source_code(ENTRY_SOURCE_STATUS)
    if category == 3:
        return entry_source_code(ENTRY_SOURCE_DEFENSE)
    element = safe_int(params_raw, 0, -1)
    if element > 0:
        return entry_source_code(ENTRY_SOURCE_USED_ELEMENT, element)
    return None


def _element_mask(value: object) -> int:
    values: tuple[object, ...]
    if isinstance(value, tuple):
        values = value
    else:
        values = (value,)
    mask = 0
    for raw in values:
        try:
            element = int(raw)
        except (TypeError, ValueError):
            continue
        if element > 0:
            mask |= 1 << element
    return mask


def _base_ids_from_buff_ids(buff_ids: list[int], buff_conf: dict[int, dict]) -> list[int]:
    out: list[int] = []
    for buff_id in buff_ids:
        rec = buff_conf.get(buff_id) or {}
        for base_id in rec.get("buff_base_ids") or ():
            if base_id:
                out.append(int(base_id))
    return out


def _param_int(params: tuple, index: int, default: int = 0) -> int:
    if index >= len(params):
        return default
    value = params[index]
    if isinstance(value, tuple):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


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
