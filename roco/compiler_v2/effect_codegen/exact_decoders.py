"""Generated exact effect decoders.

The old hand-maintained effect_id table has moved into pak structural
family decoders.  This module only adapts generated exact tables whose
keys are still effect ids, currently weather setters.
"""

from __future__ import annotations

from roco.compiler_v2.static_artifacts.weather import build_weather_effect_decoders

from roco.compiler_v2.effect_codegen.outcomes import EmitOutcome


def _weather_outcomes() -> dict[int, EmitOutcome | tuple[EmitOutcome, str]]:
    """Adapt :data:`WEATHER_EFFECT_DECODERS` (tuples) to outcome form."""
    out: dict[int, EmitOutcome | tuple[EmitOutcome, str]] = {}
    for eid, row in build_weather_effect_decoders().items():
        primitive, p0, p1, p2, p3, timing_override = row
        outcome = EmitOutcome(primitive, p0, p1, p2, p3, 1)
        out[int(eid)] = (outcome, int(timing_override)) if timing_override else outcome
    return out


EXACT_EFFECT_DECODERS: dict[int, EmitOutcome | tuple[EmitOutcome, str]] = {
    **_weather_outcomes(),
}


def decode_exact(
    effect_id: int,
) -> EmitOutcome | tuple[EmitOutcome, str] | None:
    """Return the curated outcome for ``effect_id``, or ``None`` to fall through."""
    return EXACT_EFFECT_DECODERS.get(effect_id)
