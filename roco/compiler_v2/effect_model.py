"""Compiled effect primitives and trigger timings.

The pak-prefix → debug-name table lives in :mod:`roco.generated.pak_ops`
(regenerated from BUFF_CONF and engine ``op_meta`` declarations).  This
module now only carries the small ``Timing`` enum (pak ``cast_moment`` plus
compiler-owned pre-resolution timings) and the compiled dataclasses used by
the data layer.

The legacy ``PakOp`` enum has been retired: its prefix members were a
hand-mirrored copy of pak schema that would drift on every pak update,
and the kernel never used it — runtime dispatch is keyed by handler
indices, not pak prefixes.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from types import MappingProxyType
from typing import Any


EMPTY_PARAMS = MappingProxyType({})


# ---------------------------------------------------------------------------
# Timing -- pak cast_moment values plus compiler-owned pre-resolution hooks.
# ---------------------------------------------------------------------------

class Timing(IntEnum):
    """Effect trigger points used by generated kernel rows."""

    CALC_DAMAGE = 6       # pre-attack setup
    CHECK_HIT = 7         # post-hit
    FAINT = 9             # faint trigger
    TURN_START = 10       # turn start
    AFTER_MOVE = 11       # main effect resolution
    TURN_END = 12         # end of turn
    PASSIVE_PERSIST = 23  # passive persistent
    SWITCH_IN = 24        # switch in
    CHARGE = 25           # charge/prep
    PASSIVE_COND = 26     # passive conditional
    BATTLE_START = 27     # entry aura
    BEFORE_MOVE = 901     # compiler-owned hook before cost payment/damage


# ---------------------------------------------------------------------------
# Dataclasses used by the data-catalog layer
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class EffectSpec:
    """One compiled effect row keyed by kernel handler index."""

    tag: int                                    # kernel handler index
    timing: Timing
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
