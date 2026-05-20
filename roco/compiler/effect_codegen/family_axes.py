"""Pak-axis family decoders.

Each decoder keys on a pak schema axis (currently
``EFFECT_CONF.effect_order``; ``BUFFBASE_CONF.buffbase_order`` arrives
in Phase 7C) rather than a hand-curated effect_id list.  Family axes
are the source of truth: pak's own schema field tells us which kernel
op to emit, so we don't need to maintain N hand-written rule rows for
N effect_ids that all share one axis value.

Public entry point: :func:`decode_family_axes`.  Returns the same
shape as :func:`decode_exact` —
``EmitOutcome | (EmitOutcome, timing_override) | None`` — so the
orchestrator in :mod:`roco.compiler.effect_codegen` can chain the two
loaders with no special-case handling: family axes win first
(pak-native), then hand-curated overrides, then structural fallback.

Adding a new family axis: append a branch in
:func:`decode_family_axes` that reads the corresponding pak field and
delegates to a small private helper.  Keep the helpers pak-only —
they must not consult rule JSONL files or the kernel.
"""

from __future__ import annotations

from roco.generated.handler_indices import H_INSTALL_COUNTER

from roco.compiler.effect_codegen.outcomes import EmitOutcome
from roco.compiler.effect_codegen.params import safe_int


# Pak ``effect_order`` values handled by this module.  One enum-ish
# value per family axis; keep names mirrored from Lua's
# ``Enum.EffectType`` where applicable so a reader can cross-reference
# pak's own naming.
ET_COUNTER = 31  # SkillPerformAutoBattleUtils.lua:189 (`EffectConf.effect_order == ET_COUNTER`)

# Counter-trigger install must always run AFTER_MOVE so the kernel can
# fold ``actor_counter_install_skill_id`` into ``SideState.counter_skill_id``
# in time for the next incoming hit.  Pak skill_result entries sometimes
# carry ``cast_moment`` other than 11 (observed: 6, 7, 12) — the override
# normalises the install window so the counter is always armed at the
# correct stage regardless of how the calling skill schedules it.
COUNTER_INSTALL_TIMING = 11


def decode_family_axes(
    effect_id: int,
    effect_conf: dict[int, dict],
    buff_conf: dict[int, dict],  # noqa: ARG001 — reserved for buffbase_order families (7C)
) -> EmitOutcome | tuple[EmitOutcome, int] | None:
    """Return a pak-family outcome for ``effect_id``, or ``None`` to fall through.

    ``buff_conf`` is unused by the current axes but accepted so 7C
    buffbase_order decoders can plug in without changing the call sites.
    """
    rec = effect_conf.get(effect_id)
    if rec is None:
        return None
    order = int(rec.get("effect_order", 0))
    if order == ET_COUNTER:
        return _decode_counter_install(rec)
    return None


def _decode_counter_install(rec: dict) -> tuple[EmitOutcome, int] | None:
    """Build an ``H_INSTALL_COUNTER`` emit from a pak ``effect_order=31`` row.

    ``effect_param[0].params[0]`` is the 70xxxxx response skill_id that
    fires on the next incoming hit.  Returns ``None`` when the slot is
    empty or out of the response-skill id range — those records will
    surface as gaps downstream rather than installing a bogus counter.
    """
    params_raw = rec.get("effect_param") or rec.get("params") or []
    response_skill_id = safe_int(params_raw, 0)
    if not (7000000 <= response_skill_id < 8000000):
        return None
    outcome = EmitOutcome(
        handler_idx=H_INSTALL_COUNTER,
        p0=response_skill_id,
        p1=0,
        p2=0,
        p3=0,
        stacks=1,
    )
    return outcome, COUNTER_INSTALL_TIMING
