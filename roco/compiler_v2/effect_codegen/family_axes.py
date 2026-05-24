"""Pak-axis family decoder public facade.

Concrete decoders live under :mod:`family_axis_decoders` so this module
stays as the stable import surface used by the generator and tests.
"""

from __future__ import annotations

from roco.compiler_v2.effect_codegen.family_axis_decoders import decode_family_axes
from roco.compiler_v2.effect_codegen.family_axis_decoders.common import (
    COUNTER_INSTALL_TIMING,
    COUNT_FAINTED_ALLY,
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
    SWITCH_IN_TIMING,
)

__all__ = [
    "COUNTER_INSTALL_TIMING",
    "COUNT_FAINTED_ALLY",
    "ET_BUFF_BY_CHANGE_TIMES",
    "ET_BUFF_BY_EQUIP_SKILL_NUM",
    "ET_BUFF_BY_PACK_PET_NUM",
    "ET_BUFF_CONVERT",
    "ET_COPY_BUFF",
    "ET_COUNTER",
    "ET_EXCHANGE_RATIO_OR_STATE",
    "ET_EXCHANGE_SKILLS",
    "ET_HEAL_ENERGY",
    "ET_HEAL_HP",
    "ET_HERO",
    "ET_HIT_COUNT",
    "ET_LIFE_DRAIN",
    "ET_LIMIT_FIGHT_BY_HP",
    "ET_PRIORITY_NEXT",
    "ET_PURIFY",
    "ET_SET_COOLDOWN",
    "SWITCH_IN_TIMING",
    "decode_family_axes",
]
