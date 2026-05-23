"""Four-state decoder outcome — no H_NOOP at the compiler boundary.

Every pak skill_result entry decodes to exactly one of these:

* :class:`EmitOutcome` — produces a runtime row (kernel handler index > 0).
  Routed to ``skill_effects`` / ``ability_effects``.
* :class:`IgnoredOutcome` — pak/Lua evidence shows no combat semantics
  (animation hooks, visual-only buffs).  Routed to ``ignored_effects``.
* :class:`GapOutcome` — unsupported / unrecognised.  Routed to
  ``effect_gaps``.  ``used_count > 0`` blocks strict ``build_db``.
* :class:`AbilityFlagOutcome` — pak effect that compiles into an
  ``ABILITY_FLAGS`` bit on the owning ability, not a runtime row.
  Routed nowhere directly; the bit is set by ``compiler_v2.ability_flags``
  via the join ``ability_effect_ids`` × pak-derived ability flag semantics.
  Only the ability decoding path may surface this outcome — the skill
  builder calls ``generate_effect_rows(allow_ability_flags=False)`` so a
  leak (effect_id mis-routed to a skill_result) becomes a loud error.

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
    pak_table: str         # 'EFFECT_CONF' / 'BUFF_CONF' / generated family name


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
      semantics must not be silently applied to a per-cast skill row.
    * Ability path — :func:`build_ability_effect_rows` passes
      ``allow_ability_flags=True``; the outcome is then **dropped** from
      the row / ignored / gap lists.  The bit is set later by
      ``compiler_v2.ability_flags.populate()`` via the
      ``ability_effect_ids`` table join.
    """
    effect_id: int
    flag_name: str
