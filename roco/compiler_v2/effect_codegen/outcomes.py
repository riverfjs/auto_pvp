"""Decoder outcomes — no H_NOOP or silent discard at the compiler boundary.

Every pak skill_result entry decodes to exactly one of these:

* :class:`EmitOutcome` — produces a runtime row (kernel handler index > 0).
  Routed to generated skill/ability effect rows.
* :class:`GapOutcome` — unsupported / unrecognised.  Routed to
  generated audit/debug gap metadata.
* :class:`AbilityFlagOutcome` — pak effect that compiles into an
  ``ABILITY_FLAGS`` bit on the owning ability, not a runtime row.
  Routed nowhere directly; the bit is set by ``compiler_v2.ability_flags``
  via the join of generated ``ability_effect_ids`` provenance ×
  pak-derived ability flag semantics.
  Only the ability decoding path may surface this outcome — the skill
  builder calls ``generate_effect_rows(allow_ability_flags=False)`` so a
  leak (effect_id mis-routed to a skill_result) becomes a loud error.

Decoders may emit a *list* of outcomes (some pak effects map to multiple
rows). Unsupported pak semantics must remain a :class:`GapOutcome`;
there is intentionally no runtime discard outcome.
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
class GapOutcome:
    primitive: str
    effect_id: int | None
    buff_id: int | None
    reason: str
    params: dict


@dataclass(frozen=True)
class AbilityFlagOutcome:
    """A pak effect that compiles into an ``ABILITY_FLAGS`` bit, not a row.

    Emitted by :func:`classify.decode_effect` when the pak ``effect_id`` is
    derived as an ability-flag effect.  Carries the pak
    ``effect_id`` plus the :class:`roco.common.enums.AbilityFlag` member
    *name* (the bit value is looked up by name in codegen so the rule file
    never encodes raw integers).

    Downstream:

    * Skill path — :func:`generate_effect_rows(allow_ability_flags=False)`
      raises ``RuntimeError`` if it sees one, since ability-passive
      semantics must not be applied to a per-cast skill row.
    * Ability path — :func:`build_ability_effect_rows` passes
      ``allow_ability_flags=True``; the outcome is then **dropped** from
      the row / gap lists.  The bit is set later by
      ``compiler_v2.ability_flags.populate()`` via the
      ``ability_effect_ids`` table join.
    """
    effect_id: int
    flag_name: str
