"""Reusable runtime predicates and counters for pak-compiled rows."""

from __future__ import annotations

from roco.common.enums import Element
from roco.common.entry_sources import (
    ENTRY_SOURCE_COUNTER,
    ENTRY_SOURCE_DEFENSE,
    ENTRY_SOURCE_ENEMY_SKILL_DAM_TYPE,
    ENTRY_SOURCE_ENEMY_SWITCH,
    ENTRY_SOURCE_EQUIPPED_ELEMENT,
    ENTRY_SOURCE_STATUS,
    ENTRY_SOURCE_USED_ELEMENT,
)
from roco.common.packing import _unpack_skill_count, _unpack_u8_count
from roco.engine.kernel.ctx import StageCtx


def slot_mask_matches(ctx: StageCtx, mask: int) -> bool:
    return ctx.skill_slot >= 0 and bool(mask & (1 << ctx.skill_slot))


def entry_source_count(ctx: StageCtx, source_code: int) -> int:
    source = source_code & 0xFF
    source_element = source_code >> 8
    if source == ENTRY_SOURCE_USED_ELEMENT:
        return _unpack_skill_count(ctx.side_skill_counts, Element(source_element))
    if source == ENTRY_SOURCE_COUNTER:
        return ctx.side_counter_count
    if source == ENTRY_SOURCE_STATUS:
        return ctx.side_status_skill_count
    if source == ENTRY_SOURCE_DEFENSE:
        return ctx.side_defense_skill_count
    if source == ENTRY_SOURCE_EQUIPPED_ELEMENT:
        return _unpack_skill_count(ctx.side_equipped_skill_counts, Element(source_element))
    if source == ENTRY_SOURCE_ENEMY_SKILL_DAM_TYPE:
        return _unpack_u8_count(ctx.enemy_skill_dam_type_counts, source_element)
    if source == ENTRY_SOURCE_ENEMY_SWITCH:
        return ctx.enemy_switch_count
    raise RuntimeError(f"unknown entry source code: {source_code}")
