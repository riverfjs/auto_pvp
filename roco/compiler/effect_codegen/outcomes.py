"""Three-state decoder outcome — no H_NOOP at the compiler boundary.

Every pak skill_result entry decodes to exactly one of these:

* :class:`EmitOutcome` — produces a runtime row (kernel handler index > 0).
* :class:`IgnoredOutcome` — pak/Lua evidence shows no combat semantics
  (animation hooks, visual-only buffs).  Routed to ``ignored_effects``.
* :class:`GapOutcome` — unsupported / unrecognised.  Routed to
  ``effect_gaps``.  ``used_count > 0`` blocks strict ``build_db``.

Decoders may emit a *list* of outcomes (some pak effects map to multiple
rows; gaps and ignored stay scalar but live in the same list for
uniform iteration).  The pipeline in :mod:`.__init__` splits the list.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EmitOutcome:
    handler_idx: int   # > 0 by construction; H_NOOP forbidden
    p0: int
    p1: int
    p2: int
    p3: int
    stacks: int        # pak-encoded repeat count, 1 when not stacked


@dataclass(frozen=True)
class IgnoredOutcome:
    primitive: str         # 'effect_<id>' / 'buff_<id>' / 'prefix_<n>'
    effect_id: int | None  # None when input was a direct buff_id
    buff_id: int | None    # None when input was an effect_id
    reason: str            # short label e.g. 'visual_only_animation'
    evidence: str          # pak/Lua quote or path proving no combat semantics
    pak_table: str         # 'EFFECT_CONF' / 'BUFF_CONF' / 'prefix_handlers'


@dataclass(frozen=True)
class GapOutcome:
    primitive: str
    effect_id: int | None
    buff_id: int | None
    reason: str
    params: dict
