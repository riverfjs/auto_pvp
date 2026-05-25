"""Compiled effect primitives.

The generated pak-prefix debug table is emitted from BUFF_CONF and primitive
axis declarations.  Timing is no longer a compiler enum: pak timings are
emitted as ``battle_event:<Enum.BattleEvent symbol>`` keys, and engine-only
hooks are emitted as ``engine_hook:<name>`` keys.

The legacy ``PakOp`` enum has been retired: its prefix members were a
hand-mirrored copy of pak schema that would drift on every pak update,
and the kernel never used it — compiler output is keyed by primitive strings,
not pak prefixes.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any


EMPTY_PARAMS = MappingProxyType({})


# ---------------------------------------------------------------------------
# Dataclasses used by the data-catalog layer
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class EffectSpec:
    """One compiler effect row keyed by pak-derived primitive key."""

    primitive_key: str
    timing: str
    params: MappingProxyType[str, Any] = EMPTY_PARAMS
    chance: float = 1.0
    condition: str = ""


@dataclass(slots=True)
class SkillEffect:
    skill_id: int
    effect: EffectSpec
    sort_order: int = 0


@dataclass(slots=True)
class AbilityEffect:
    ability_id: int
    effect: EffectSpec
    sort_order: int = 0
