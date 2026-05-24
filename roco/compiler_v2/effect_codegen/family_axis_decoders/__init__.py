"""Dispatch for pak-native effect family decoders."""

from __future__ import annotations

from roco.common.primitive_keys import effect_order_key
from roco.compiler_v2.effect_codegen.outcomes import EmitOutcome

from roco.compiler_v2.effect_codegen.family_axis_decoders.basic import (
    decode_copy_buff,
    decode_counter_install,
    decode_exchange_ratio_or_state,
    decode_exchange_skills,
    decode_heal_energy,
    decode_hit_count_delta,
    decode_priority_next,
    decode_purify,
    decode_self_cooldown,
)
from roco.compiler_v2.effect_codegen.family_axis_decoders.common import (
    ET_BUFF_BY_CHANGE_TIMES,
    ET_BUFF_BY_EQUIP_SKILL_NUM,
    ET_BUFF_BY_PACK_PET_NUM,
    ET_BUFF_CONVERT,
    ET_COPY_BUFF,
    ET_COUNTER,
    ET_EXCHANGE_RATIO_OR_STATE,
    ET_EXCHANGE_SKILLS,
    ET_HEAL_ENERGY,
    ET_HEAL_HP,
    ET_HERO,
    ET_HIT_COUNT,
    ET_LIFE_DRAIN,
    ET_LIMIT_FIGHT_BY_HP,
    ET_PRIORITY_NEXT,
    ET_PURIFY,
    ET_SET_COOLDOWN,
    emit_from_param,
)
from roco.compiler_v2.effect_codegen.family_axis_decoders.entry import (
    decode_buff_by_equip_skill_num,
    decode_buff_by_pack_pet_num,
    decode_entry_buff_if_energy,
    decode_entry_static_buff,
    decode_hero_entry,
)
from roco.compiler_v2.effect_codegen.family_axis_decoders.marks import decode_buff_convert


def decode_family_axes(
    effect_id: int,
    effect_conf: dict[int, dict],
    buff_conf: dict[int, dict],
) -> EmitOutcome | tuple[EmitOutcome, str] | None:
    """Return a pak-family outcome for ``effect_id``, or ``None`` to fall through."""
    rec = effect_conf.get(effect_id)
    if rec is None:
        return None
    order = int(rec.get("effect_order", 0))
    effect_type = int(rec.get("type", 0) or 0)
    if order == ET_PURIFY and effect_type == 1:
        return decode_purify(rec)
    if order == ET_HEAL_HP and effect_type == 1:
        return emit_from_param(rec, effect_order_key("ET_RECOVER"), 1)
    if order == ET_LIFE_DRAIN and effect_type == 1:
        return emit_from_param(rec, effect_order_key("ET_SUCKBLOOD"), 0)
    if order == ET_HEAL_ENERGY and effect_type == 3:
        return decode_heal_energy(rec)
    if order == ET_BUFF_BY_PACK_PET_NUM and effect_type == 3:
        return decode_buff_by_pack_pet_num(rec, buff_conf)
    if order == ET_COUNTER:
        return decode_counter_install(rec)
    if order == ET_HERO and effect_type == 3:
        return decode_hero_entry(rec, buff_conf)
    if order == ET_HIT_COUNT and effect_type == 1:
        return decode_hit_count_delta(rec)
    if order == ET_SET_COOLDOWN and effect_type == 3:
        return decode_self_cooldown(rec)
    if order == ET_BUFF_CONVERT and effect_type == 1:
        return decode_buff_convert(rec, buff_conf)
    if order == ET_EXCHANGE_RATIO_OR_STATE and effect_type == 3:
        return decode_exchange_ratio_or_state(rec)
    if order == ET_EXCHANGE_SKILLS and effect_type == 3:
        return decode_exchange_skills(rec)
    if order == ET_COPY_BUFF and effect_type == 1:
        return decode_copy_buff(rec)
    if order == ET_PRIORITY_NEXT and effect_type == 1:
        return decode_priority_next(rec)
    if order == ET_BUFF_BY_CHANGE_TIMES and effect_type == 3:
        return decode_entry_static_buff(rec, buff_conf)
    if order == ET_BUFF_BY_EQUIP_SKILL_NUM and effect_type == 3:
        return decode_buff_by_equip_skill_num(rec, buff_conf)
    if order == ET_LIMIT_FIGHT_BY_HP and effect_type == 3:
        return decode_entry_buff_if_energy(rec, buff_conf)
    return None
