"""Loader for the hand-curated effect_id → outcome table.

Two sources feed :data:`EXACT_EFFECT_DECODERS`:

1. :file:`roco/compiler/rules/exact_effects.jsonl` — single-mapping
   pak effects whose semantics need a human decision.  Each row carries
   a ``kind`` discriminator:

   * ``kind: "emit"`` (default) — requires ``handler`` (resolved against
     :mod:`roco.generated.handler_indices`; ``H_NOOP`` is **rejected**)
     and ``args`` (four ints).  Optional ``timing_override``.  Loads as
     :class:`EmitOutcome`.
   * ``kind: "ignored"`` — pak/Lua proves no combat semantics.  Requires
     ``reason`` + ``evidence`` (pak/Lua citation).  Forbids ``handler``
     / ``args``.  Loads as :class:`IgnoredOutcome`.

   The ``evidence`` field is mandatory on every row so a reader can
   verify the mapping against pak/Lua without grepping kernel code.

2. :mod:`roco.generated.weather_decoders` — auto-derived from pak by
   ``gen_prefix_map``.  pak ``effect_param[0]`` is the pak weather
   code; the generator resolves it to a kernel ``WeatherType`` value
   and picks a default duration.
"""

from __future__ import annotations

import json
from pathlib import Path

from roco.generated import handler_indices as _hi
from roco.generated.weather_decoders import WEATHER_EFFECT_DECODERS

from roco.compiler.effect_codegen.outcomes import EmitOutcome, IgnoredOutcome


_RULES_PATH = Path(__file__).resolve().parents[2] / "compiler" / "rules" / "exact_effects.jsonl"


def _load_jsonl() -> dict[int, EmitOutcome | IgnoredOutcome | tuple[EmitOutcome, int]]:
    """Parse ``exact_effects.jsonl`` into ``effect_id`` → outcome (+ optional timing).

    Returns a dict keyed by effect_id.  Values are either:

    * ``EmitOutcome`` (no timing override)
    * ``(EmitOutcome, timing_override)`` tuple when the JSONL row sets
      ``timing_override`` to override pak's ``cast_moment``
    * ``IgnoredOutcome``

    Loader-level invariants:

    * ``kind`` defaults to ``"emit"``.
    * ``handler: "H_NOOP"`` is rejected — H_NOOP is not a valid compile
      result; if pak/Lua proves no combat semantics, use
      ``kind: "ignored"`` instead.
    * Unknown handler names are rejected (catch kernel renames).
    """
    out: dict[int, EmitOutcome | IgnoredOutcome | tuple[EmitOutcome, int]] = {}
    with _RULES_PATH.open("r", encoding="utf-8") as fp:
        for line_no, raw in enumerate(fp, 1):
            raw = raw.strip()
            if not raw or raw.startswith("#"):
                continue
            rec = json.loads(raw)
            effect_id = int(rec["effect_id"])
            kind = rec.get("kind", "emit")

            if kind == "ignored":
                if "handler" in rec or "args" in rec:
                    raise RuntimeError(
                        f"exact_effects.jsonl line {line_no}: ``kind: ignored`` "
                        f"forbids ``handler``/``args`` fields"
                    )
                reason = rec.get("reason") or ""
                evidence = rec.get("evidence") or ""
                if not reason or not evidence:
                    raise RuntimeError(
                        f"exact_effects.jsonl line {line_no}: ``kind: ignored`` "
                        f"requires both ``reason`` and ``evidence`` fields"
                    )
                out[effect_id] = IgnoredOutcome(
                    primitive=f"effect_{effect_id}",
                    effect_id=effect_id,
                    buff_id=None,
                    reason=reason,
                    evidence=evidence,
                    pak_table=rec.get("pak_table", "EFFECT_CONF"),
                )
                continue

            if kind != "emit":
                raise RuntimeError(
                    f"exact_effects.jsonl line {line_no}: unknown kind {kind!r} "
                    f"(expected 'emit' or 'ignored')"
                )

            handler_name = rec["handler"]
            if handler_name == "H_NOOP":
                raise RuntimeError(
                    f"exact_effects.jsonl line {line_no}: ``handler: H_NOOP`` "
                    f"is forbidden — use ``kind: ignored`` for pak-confirmed "
                    f"non-combat effects, or remove the row so the effect "
                    f"falls through to the gap path"
                )
            if not hasattr(_hi, handler_name):
                raise RuntimeError(
                    f"exact_effects.jsonl line {line_no}: unknown handler "
                    f"'{handler_name}'"
                )
            handler_idx = int(getattr(_hi, handler_name))
            args = rec.get("args") or [0, 0, 0, 0]
            if len(args) != 4:
                raise RuntimeError(
                    f"exact_effects.jsonl line {line_no}: ``args`` must have 4 entries"
                )
            outcome = EmitOutcome(
                handler_idx=handler_idx,
                p0=int(args[0]),
                p1=int(args[1]),
                p2=int(args[2]),
                p3=int(args[3]),
                stacks=1,
            )
            timing_override = int(rec.get("timing_override", 0))
            out[effect_id] = (outcome, timing_override) if timing_override else outcome
    return out


def _weather_outcomes() -> dict[int, EmitOutcome | tuple[EmitOutcome, int]]:
    """Adapt :data:`WEATHER_EFFECT_DECODERS` (tuples) to outcome form."""
    out: dict[int, EmitOutcome | tuple[EmitOutcome, int]] = {}
    for eid, row in WEATHER_EFFECT_DECODERS.items():
        h, p0, p1, p2, p3, timing_override = row
        outcome = EmitOutcome(h, p0, p1, p2, p3, 1)
        out[int(eid)] = (outcome, int(timing_override)) if timing_override else outcome
    return out


EXACT_EFFECT_DECODERS: dict[int, EmitOutcome | IgnoredOutcome | tuple[EmitOutcome, int]] = {
    **_load_jsonl(),
    **_weather_outcomes(),
}


def decode_exact(
    effect_id: int,
) -> EmitOutcome | IgnoredOutcome | tuple[EmitOutcome, int] | None:
    """Return the curated outcome for ``effect_id``, or ``None`` to fall through."""
    return EXACT_EFFECT_DECODERS.get(effect_id)
