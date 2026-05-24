"""Engine-owned binding from pak-derived primitive keys to handler constants."""

from __future__ import annotations

import importlib
from functools import lru_cache

from roco.common.primitive_keys import (
    buff_type_key,
    effect_kind_key,
    effect_order_key,
    effect_order_variant_key,
    mark_note_key,
    source_context_key,
    status_note_key,
    struct_key,
)
from roco.engine.kernel.handler_manifest import OP_MODULES, func_to_const
from roco.engine.kernel.op_meta import (
    HANDLES_BUFF_ATTR,
    HANDLES_MARK_ATTR,
    HANDLES_PREFIX_ATTR,
)
from roco.generated import handler_indices as hi


EXACT_PRIMITIVE_BINDINGS: dict[str, str] = {
    effect_kind_key(2): "H_DAMAGE",
    effect_order_key("ET_PURIFY"): "H_DISPEL_DEBUFFS",
    effect_order_key("ET_RECOVER"): "H_HEAL_HP",
    effect_order_key("ET_SUCKBLOOD"): "H_LIFE_DRAIN",
    effect_order_key("ET_CHANGE_ENERGY"): "H_HEAL_ENERGY",
    effect_order_key("ET_COUNTER"): "H_INSTALL_COUNTER",
    effect_order_key("ET_MULTIPLE"): "H_HIT_COUNT_DELTA",
    effect_order_key("ET_SKILL_CD"): "H_SET_SELF_COOLDOWN",
    effect_order_key("ET_FAST_SKILL"): "H_PRIORITY_NEXT_DELTA",
    effect_order_key("ET_SWAP_SKILLS"): "H_EXCHANGE_MOVES",
    effect_order_key("ET_COPY_BUFF"): "H_MIRROR_ENEMY_BUFFS",
    effect_order_key("ET_CHANGE_WEATHER"): "H_WEATHER",
    effect_order_key("ET_BUFF_BY_CHANGE_TIMES"): "H_SELF_BUFF",
    effect_order_variant_key("ET_BUFF_BY_PACK_PET_NUM", "entry_self_buff_by_side_count"):
        "H_ENTRY_SELF_BUFF_BY_SIDE_COUNT",
    effect_order_variant_key("ET_LIMIT_FIGHT_BY_HP", "entry_self_buff_if_energy"):
        "H_ENTRY_SELF_BUFF_IF_ENERGY",
    effect_order_variant_key("ET_HERO", "entry_self_buff_by_source_count"):
        "H_ENTRY_SELF_BUFF_BY_SOURCE_COUNT",
    effect_order_variant_key("ET_HERO", "entry_self_buff_by_used_skill_count"):
        "H_ENTRY_SELF_BUFF_BY_USED_SKILL_COUNT",
    effect_order_variant_key("ET_HERO", "entry_buff_per_skill_count"):
        "H_ENTRY_BUFF_PER_SKILL_COUNT",
    effect_order_variant_key("ET_HERO", "entry_element_skill_mod_by_count"):
        "H_ENTRY_ELEMENT_SKILL_MOD_BY_COUNT",
    effect_order_variant_key("ET_BUFF_BY_EQUIP_SKILL_NUM", "entry_element_skill_mod_by_count"):
        "H_ENTRY_ELEMENT_SKILL_MOD_BY_COUNT",
    effect_order_variant_key("ET_SWAP_STAT", "hp_ratio"): "H_EXCHANGE_HP_RATIO",
    effect_order_variant_key("ET_SWAP_STAT", "transfer_mods"): "H_TRANSFER_MODS",
    effect_order_variant_key("ET_BUFF_CONVERT", "dispel_marks"): "H_DISPEL_MARKS",
    effect_order_variant_key("ET_BUFF_CONVERT", "dispel_marks_to_burn"):
        "H_DISPEL_MARKS_TO_BURN",
    source_context_key("hit_count_per_poison_effect"): "H_HIT_COUNT_PER_POISON_EFFECT",
    source_context_key("cute_hit_per_stack"): "H_CUTE_HIT_PER_STACK",
    source_context_key("slot_skill_mod"): "H_SKILL_MOD",
    status_note_key("中毒"): "H_POISON",
    status_note_key("灼烧"): "H_BURN",
    status_note_key("寄生"): "H_LEECH",
    struct_key("zero_energy_auto_switch"): "H_AUTO_SWITCH_ON_ZERO_ENERGY",
    struct_key("team_skill_hit_count"): "H_HIT_COUNT_BY_TEAM_SKILL_COUNT",
    struct_key("flat_hit_count_delta"): "H_HIT_COUNT_DELTA",
    struct_key("heal_reversal"): "H_ANTI_HEAL",
    struct_key("cute_bench_cost_reduce"): "H_CUTE_BENCH_COST_REDUCE",
}


@lru_cache(maxsize=1)
def primitive_bindings() -> dict[str, str]:
    bindings = dict(EXACT_PRIMITIVE_BINDINGS)
    for mod_name in OP_MODULES:
        module = importlib.import_module(mod_name)
        for name in dir(module):
            if not name.startswith("op_"):
                continue
            func = getattr(module, name)
            const = func_to_const(name)
            for symbol, _alias in getattr(func, HANDLES_BUFF_ATTR, ()):
                _put_binding(bindings, buff_type_key(str(symbol)), const)
            for symbol, _alias in getattr(func, HANDLES_PREFIX_ATTR, ()):
                _put_binding(bindings, buff_type_key(str(symbol)), const)
            for note, _mark_name in getattr(func, HANDLES_MARK_ATTR, ()):
                _put_binding(bindings, mark_note_key(str(note)), const)
    _validate_handler_constants(bindings)
    return bindings


def handler_const_from_primitive(primitive: str) -> str:
    try:
        return primitive_bindings()[primitive]
    except KeyError as exc:
        raise RuntimeError(f"primitive {primitive!r} has no engine binding") from exc


def _put_binding(bindings: dict[str, str], primitive: str, const: str) -> None:
    existing = bindings.get(primitive)
    if existing is not None and existing != const:
        raise RuntimeError(f"primitive binding conflict for {primitive!r}: {existing} vs {const}")
    bindings[primitive] = const


def _validate_handler_constants(bindings: dict[str, str]) -> None:
    missing = sorted({const for const in bindings.values() if not hasattr(hi, const)})
    if missing:
        raise RuntimeError(f"primitive bindings reference missing handlers: {', '.join(missing)}")
