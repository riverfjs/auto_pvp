"""Switch-in and history-count pak effect-order decoders."""

from __future__ import annotations

from roco.common.entry_sources import (
    ENTRY_SOURCE_COUNTER,
    ENTRY_SOURCE_DEFENSE,
    ENTRY_SOURCE_ENEMY_SKILL_DAM_TYPE,
    ENTRY_SOURCE_ENEMY_SWITCH,
    ENTRY_SOURCE_STATUS,
    ENTRY_SOURCE_USED_ELEMENT,
    entry_source_code,
)
from roco.compiler_v2.effect_codegen.buffbase_source import (
    BUFFBASE_ORDER,
    BUFFBASE_PARAMS,
    pack_buff_delta_from_buff_ids,
)
from roco.compiler_v2.effect_codegen.outcomes import EmitOutcome
from roco.compiler_v2.effect_codegen.params import extract_int_list, safe_int

from roco.compiler_v2.effect_codegen.family_axis_decoders.common import (
    COUNT_FAINTED_ALLY,
    SWITCH_IN_TIMING,
    emit_effect_order,
    emit_effect_ref,
    params,
)


def decode_buff_by_pack_pet_num(rec: dict, buff_conf: dict[int, dict]) -> tuple[EmitOutcome, str] | None:
    params_raw = params(rec)
    packed = pack_buff_delta_from_buff_ids(extract_int_list(params_raw, 3), buff_conf)
    if packed == 0:
        return None
    if safe_int(params_raw, 1) == 2:
        return emit_effect_ref(int(rec["id"])), SWITCH_IN_TIMING
    element = safe_int(params_raw, 0, -1)
    if element >= 0:
        return emit_effect_ref(int(rec["id"])), SWITCH_IN_TIMING
    return None


def decode_entry_static_buff(rec: dict, buff_conf: dict[int, dict]) -> tuple[EmitOutcome, str] | None:
    packed = pack_buff_delta_from_buff_ids(extract_int_list(params(rec), 0), buff_conf)
    if packed == 0:
        return None
    return emit_effect_order("ET_BUFF_BY_CHANGE_TIMES", packed), SWITCH_IN_TIMING


def decode_entry_buff_if_energy(rec: dict, buff_conf: dict[int, dict]) -> tuple[EmitOutcome, str] | None:
    params_raw = params(rec)
    selector = safe_int(params_raw, 2)
    if selector not in (1, 2):
        return None
    packed = pack_buff_delta_from_buff_ids(extract_int_list(params_raw, 3), buff_conf)
    if packed == 0:
        return None
    return emit_effect_ref(int(rec["id"])), SWITCH_IN_TIMING


def decode_hero_entry(rec: dict, buff_conf: dict[int, dict]) -> tuple[EmitOutcome, str] | None:
    params_raw = params(rec)
    effect_id = int(rec["id"])
    event_count_buff = _decode_hero_event_count_buff(effect_id, params_raw, buff_conf)
    if event_count_buff is not None:
        return event_count_buff
    if safe_int(params_raw, 3) != 1:
        return None
    skill_count_mod = _decode_entry_buff_per_used_skill_count(effect_id, params_raw, buff_conf)
    if skill_count_mod is not None:
        return skill_count_mod
    source = _hero_count_source(params_raw)
    if source is not None:
        element_mod = _emit_raw_entry_element_mod(
            effect_id,
            source,
            _base_ids_from_buff_ids(extract_int_list(params_raw, 4), buff_conf),
        )
        if element_mod is not None:
            return element_mod
    packed = pack_buff_delta_from_buff_ids(extract_int_list(params_raw, 4), buff_conf)
    if packed == 0:
        return None
    element = safe_int(params_raw, 0, -1)
    if element > 0:
        return emit_effect_ref(effect_id), SWITCH_IN_TIMING
    return None


def decode_buff_by_equip_skill_num(rec: dict, buff_conf: dict[int, dict]) -> tuple[EmitOutcome, str] | None:
    params_raw = params(rec)
    source_skill_dam_type = safe_int(params_raw, 0, -1)
    return _emit_raw_entry_element_mod(
        int(rec["id"]),
        source_skill_dam_type,
        _base_ids_from_buff_ids(extract_int_list(params_raw, 4), buff_conf),
    )


def _emit_raw_entry_element_mod(
    effect_id: int,
    source_code: int,
    base_ids: list[int],
) -> tuple[EmitOutcome, str] | None:
    if not base_ids or len(base_ids) > 3:
        return None
    return emit_effect_ref(effect_id), SWITCH_IN_TIMING


def _decode_hero_event_count_buff(
    effect_id: int,
    params_raw: list,
    buff_conf: dict[int, dict],
) -> tuple[EmitOutcome, str] | None:
    if safe_int(params_raw, 3) != 2:
        return None
    packed = pack_buff_delta_from_buff_ids(extract_int_list(params_raw, 4), buff_conf)
    if packed == 0:
        return None
    skill_dam_type = safe_int(params_raw, 0)
    if skill_dam_type > 0:
        return emit_effect_ref(effect_id), SWITCH_IN_TIMING
    if safe_int(params_raw, 7) == 3:
        return emit_effect_ref(effect_id), SWITCH_IN_TIMING
    return None


def _decode_entry_buff_per_used_skill_count(
    effect_id: int,
    params_raw: list,
    buff_conf: dict[int, dict],
) -> tuple[EmitOutcome, str] | None:
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
            return emit_effect_ref(effect_id), SWITCH_IN_TIMING
    if order == 23 and len(base_params) >= 6:
        affected = base_params[0]
        mode = _param_int(base_params, 4)
        amount = _param_int(base_params, 5)
        if affected == 0 and mode == 2 and amount > 0:
            return emit_effect_ref(effect_id), SWITCH_IN_TIMING
    return None


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


def _base_ids_from_buff_ids(buff_ids: list[int], buff_conf: dict[int, dict]) -> list[int]:
    out: list[int] = []
    for buff_id in buff_ids:
        rec = buff_conf.get(buff_id) or {}
        for base_id in rec.get("buff_base_ids") or ():
            if base_id:
                out.append(int(base_id))
    return out


def _param_int(params_raw: tuple, index: int, default: int = 0) -> int:
    if index >= len(params_raw):
        return default
    value = params_raw[index]
    if isinstance(value, tuple):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
