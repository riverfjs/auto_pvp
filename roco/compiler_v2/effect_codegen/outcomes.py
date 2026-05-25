"""Decoder outcomes — primitive rows, no engine handlers at compiler boundary.

Every pak skill_result entry decodes to exactly one of these:

* :class:`EmitOutcome` — produces a primitive row.  The engine linker later
  maps ``primitive`` to a concrete kernel handler.
* :class:`GapOutcome` — missing or malformed pak source reference.  Routed
  to generated audit/debug gap metadata.

Behavior support is resolved later by the engine artifact linker; compiler
outcomes do not encode runtime semantics.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EmitOutcome:
    primitive: str
    p0: int
    p1: int
    p2: int
    p3: int
    stacks: int        # pak-encoded repeat count, 1 when not stacked


@dataclass(frozen=True)
class GapOutcome:
    primitive: str
    effect_id: int | None
    buff_id: int | None
    reason: str
    params: dict
