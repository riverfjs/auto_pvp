"""Engine-owned binding from pak-derived primitive keys to runtime op names."""

from __future__ import annotations

import importlib
from functools import lru_cache

from roco.common.primitive_keys import (
    buff_type_key,
    effect_kind_key,
    effect_order_key,
)
from roco.engine.kernel.handler_manifest import OP_MODULES
from roco.engine.kernel.op_meta import (
    HANDLES_BUFF_ATTR,
    HANDLES_PREFIX_ATTR,
)
from roco.generated.handler_order import OP_INDEX


EXACT_PRIMITIVE_BINDINGS: dict[str, str] = {
    effect_kind_key(2): "op_damage",
    effect_order_key("ET_PURIFY"): "op_dispel_debuffs",
    effect_order_key("ET_RECOVER"): "op_heal_hp",
    effect_order_key("ET_SUCKBLOOD"): "op_life_drain",
    effect_order_key("ET_CHANGE_ENERGY"): "op_heal_energy",
    effect_order_key("ET_COUNTER"): "op_install_counter",
    effect_order_key("ET_MULTIPLE"): "op_hit_count_delta",
    effect_order_key("ET_SKILL_CD"): "op_set_self_cooldown",
    effect_order_key("ET_FAST_SKILL"): "op_priority_next_delta",
    effect_order_key("ET_SWAP_SKILLS"): "op_exchange_moves",
    effect_order_key("ET_COPY_BUFF"): "op_mirror_enemy_buffs",
    effect_order_key("ET_CHANGE_WEATHER"): "op_weather",
    effect_order_key("ET_BUFF_BY_CHANGE_TIMES"): "op_self_buff",
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
            for symbol in getattr(func, HANDLES_BUFF_ATTR, ()):
                _put_binding(bindings, buff_type_key(str(symbol)), name)
            for symbol in getattr(func, HANDLES_PREFIX_ATTR, ()):
                _put_binding(bindings, buff_type_key(str(symbol)), name)
    _validate_op_names(bindings)
    return bindings


def op_name_from_primitive(primitive: str) -> str:
    try:
        return primitive_bindings()[primitive]
    except KeyError as exc:
        raise RuntimeError(f"primitive {primitive!r} has no engine binding") from exc


def _put_binding(bindings: dict[str, str], primitive: str, const: str) -> None:
    existing = bindings.get(primitive)
    if existing is not None and existing != const:
        raise RuntimeError(f"primitive binding conflict for {primitive!r}: {existing} vs {const}")
    bindings[primitive] = const


def _validate_op_names(bindings: dict[str, str]) -> None:
    missing = sorted({name for name in bindings.values() if name not in OP_INDEX})
    if missing:
        raise RuntimeError(f"primitive bindings reference missing ops: {', '.join(missing)}")
