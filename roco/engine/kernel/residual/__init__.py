"""Post-move and end-of-turn resolution, split by phase.

Public surface (re-exported here so existing call sites keep working):

* :func:`apply_after_move` — fold ``StageCtx`` deltas back into state after
  a single actor's move; defined in :mod:`.after_move`.
* :func:`end_turn` — run the end-of-turn phase chain (leech → marks →
  ability TURN_END → skill TURN_END → weather → status → cost-mod tick);
  defined in :mod:`.turn_end`.
* :func:`share_gains_on_side` — distribute residual HP/energy gains to a
  random non-active ally; used by both :func:`apply_after_move` and
  mechanics' focus action; defined in :mod:`.after_move`.
* :func:`apply_status_effect` — gateway for applying burn/poison/freeze/
  leech stacks with immunity checks; defined in :mod:`.status_ticks`.

Internal split:

* :mod:`.after_move` — ``apply_after_move`` and its private helpers.
* :mod:`.status_ticks` — burn/poison/leech application and ticks.
* :mod:`.weather_ticks` — per-weather residuals and weather decay.
* :mod:`.mark_ticks` — poison-mark damage and solar-mark energy gain.
* :mod:`.turn_end` — ``end_turn`` orchestration and the two turn-end
  effect runners (skill and ability).
* :mod:`._shared` — :func:`energy_cap` plus other helpers used across
  phases.
"""

from __future__ import annotations

from roco.engine.kernel.residual.after_move import apply_after_move, share_gains_on_side
from roco.engine.kernel.residual.status_ticks import apply_status_effect
from roco.engine.kernel.residual.turn_end import end_turn

__all__ = [
    "apply_after_move",
    "apply_status_effect",
    "end_turn",
    "share_gains_on_side",
]
