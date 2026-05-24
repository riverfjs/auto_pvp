"""Pak cast_moment to primitive-row timing keys."""

from __future__ import annotations

from functools import lru_cache

from roco.common.primitive_keys import battle_event_key, engine_hook_key
from roco.compiler_v2.sources import LuaEnumSource

ENGINE_HOOK_BEFORE_MOVE = engine_hook_key("before_move")


def pak_cast_moment_key(value: int) -> str:
    """Return ``battle_event:<Enum.BattleEvent symbol>`` for a pak value."""

    symbol = _battle_event_by_value().get(int(value))
    if symbol is None:
        raise RuntimeError(f"cast_moment {value!r} is not in pak Enum.BattleEvent")
    return battle_event_key(symbol)


def pak_battle_event_key(symbol: str) -> str:
    """Return a validated pak BattleEvent timing key by symbol."""

    if symbol not in _battle_event_enum():
        raise RuntimeError(f"Enum.BattleEvent has no member {symbol!r}")
    return battle_event_key(symbol)


@lru_cache(maxsize=1)
def _battle_event_enum() -> dict[str, int]:
    return LuaEnumSource().enums(("BattleEvent",))["BattleEvent"]


@lru_cache(maxsize=1)
def _battle_event_by_value() -> dict[int, str]:
    return {int(value): symbol for symbol, value in _battle_event_enum().items()}
