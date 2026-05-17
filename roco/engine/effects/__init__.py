"""Pre-registered runtime op table for compiled effect rows."""

from __future__ import annotations

from roco.engine.effect_model import EffectTag
from roco.engine.effect_registry import IMPLEMENTED_EFFECT_TAGS

from . import ability_state, core, mark
from .common import EffectOp


_ROWS = core.OP_ROWS + ability_state.OP_ROWS + mark.OP_ROWS
_MAX_TAG = max(tag.value for tag in EffectTag)
_TABLE: list[EffectOp | None] = [None] * (_MAX_TAG + 1)
for _tag, _op in _ROWS:
    _TABLE[_tag.value] = _op

OP_TABLE: tuple[EffectOp | None, ...] = tuple(_TABLE)
IMPLEMENTED_OP_TAGS = frozenset(tag for tag, _op in _ROWS)

assert IMPLEMENTED_OP_TAGS == IMPLEMENTED_EFFECT_TAGS

__all__ = ["EffectOp", "OP_TABLE", "IMPLEMENTED_OP_TAGS"]
