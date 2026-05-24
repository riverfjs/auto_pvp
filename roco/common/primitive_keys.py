"""Primitive key schema shared by compiler output and engine linking.

These helpers name pak-derived axes, not engine handlers.  The compiler emits
these keys in static rows; the engine owns the binding from key to op.
"""

from __future__ import annotations

BATTLE_EVENT_PREFIX = "battle_event:"
BUFF_TYPE_PREFIX = "buff_type:"
EFFECT_KIND_PREFIX = "effect_kind:"
EFFECT_ORDER_PREFIX = "effect_order:"
ENGINE_HOOK_PREFIX = "engine_hook:"
MARK_NOTE_PREFIX = "mark_note:"
SOURCE_CONTEXT_PREFIX = "source_context:"
STATUS_NOTE_PREFIX = "status_note:"
STRUCT_PREFIX = "struct:"


def battle_event_key(symbol: str) -> str:
    return _key(BATTLE_EVENT_PREFIX, symbol)


def buff_type_key(symbol: str) -> str:
    return _key(BUFF_TYPE_PREFIX, symbol)


def effect_kind_key(kind: int) -> str:
    return f"{EFFECT_KIND_PREFIX}{int(kind)}"


def effect_order_key(symbol: str) -> str:
    return _key(EFFECT_ORDER_PREFIX, symbol)


def effect_order_variant_key(symbol: str, variant: str) -> str:
    return f"{effect_order_key(symbol)}/{_clean(variant)}"


def engine_hook_key(name: str) -> str:
    return _key(ENGINE_HOOK_PREFIX, name)


def mark_note_key(note: str) -> str:
    return _key(MARK_NOTE_PREFIX, note)


def source_context_key(name: str) -> str:
    return _key(SOURCE_CONTEXT_PREFIX, name)


def status_note_key(note: str) -> str:
    return _key(STATUS_NOTE_PREFIX, note)


def struct_key(name: str) -> str:
    return _key(STRUCT_PREFIX, name)


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
