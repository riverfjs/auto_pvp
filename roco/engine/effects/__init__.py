"""Pre-registered runtime handler table for compiled effect rows."""

from __future__ import annotations

from roco.engine.effect_model import EffectTag
from roco.engine.effect_registry import IMPLEMENTED_EFFECT_TAGS

from . import ability_state, core, mark
from .common import EffectHandler


_ROWS = core.HANDLER_ROWS + ability_state.HANDLER_ROWS + mark.HANDLER_ROWS
_MAX_TAG = max(tag.value for tag in EffectTag)
_TABLE: list[EffectHandler | None] = [None] * (_MAX_TAG + 1)
for _tag, _handler in _ROWS:
    _TABLE[_tag.value] = _handler

HANDLER_TABLE: tuple[EffectHandler | None, ...] = tuple(_TABLE)
IMPLEMENTED_HANDLER_TAGS = frozenset(tag for tag, _handler in _ROWS)

assert IMPLEMENTED_HANDLER_TAGS == IMPLEMENTED_EFFECT_TAGS

__all__ = ["EffectHandler", "HANDLER_TABLE", "IMPLEMENTED_HANDLER_TAGS"]
