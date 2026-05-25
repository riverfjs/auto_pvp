"""Primitive key schema shared by compiler output and engine linking.

These helpers name pak-derived axes, not engine handlers.  The compiler emits
these keys in static rows; the engine owns the binding from key to op.
"""

from __future__ import annotations

BATTLE_EVENT_PREFIX = "battle_event:"
BUFF_REF_PREFIX = "buff_ref:"
BUFF_TYPE_PREFIX = "buff_type:"
EFFECT_REF_PREFIX = "effect_ref:"
EFFECT_KIND_PREFIX = "effect_kind:"
EFFECT_ORDER_PREFIX = "effect_order:"
ENGINE_HOOK_PREFIX = "engine_hook:"


def battle_event_key(symbol: str) -> str:
    return _key(BATTLE_EVENT_PREFIX, symbol)


def buff_ref_key(buff_id: int) -> str:
    return f"{BUFF_REF_PREFIX}{int(buff_id)}"


def buff_type_key(symbol: str) -> str:
    return _key(BUFF_TYPE_PREFIX, symbol)


def effect_ref_key(effect_id: int) -> str:
    return f"{EFFECT_REF_PREFIX}{int(effect_id)}"


def effect_kind_key(kind: int) -> str:
    return f"{EFFECT_KIND_PREFIX}{int(kind)}"


def effect_order_key(symbol: str) -> str:
    return _key(EFFECT_ORDER_PREFIX, symbol)


def engine_hook_key(name: str) -> str:
    return _key(ENGINE_HOOK_PREFIX, name)


def strip_prefix(value: str, prefix: str) -> str | None:
    return value[len(prefix):] if value.startswith(prefix) else None


def _key(prefix: str, value: str) -> str:
    return prefix + _clean(value)


def _clean(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError("primitive key segment cannot be empty")
    if "\n" in text or "\r" in text:
        raise ValueError(f"primitive key segment contains newline: {value!r}")
    return text
