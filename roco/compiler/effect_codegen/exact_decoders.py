"""Loader for the hand-curated effect_id → kernel row table.

Three sources feed :data:`EXACT_EFFECT_DECODERS`:

1. :file:`roco/compiler/rules/exact_effects.jsonl` — single-mapping
   pak effects whose semantics need a human decision but whose row is
   just a handler index plus literal args (cooldown, hit-count delta,
   priority, life-drain, heal HP/energy, …).  The JSONL is the editable
   surface; this module loads and validates it.

2. :mod:`roco.generated.weather_decoders` — auto-derived from pak by
   ``gen_prefix_map``.  pak ``effect_param[0]`` is the pak weather
   code; the generator resolves it to a kernel ``WeatherType`` value
   and picks a default duration.  Adding a new weather effect in pak
   only needs the pak→kernel weather code map to be extended.

3. The two compound effects below — ``1042008`` and ``1042014`` — stay
   in Python because their kernel ops are custom-built for the pak
   compound semantic (mark dispel of either side; marks-→-burn payload
   that reads ``ctx.marks_dispelled``).  Their row args are kernel
   constants by design, not pak parameter pass-through.
"""

from __future__ import annotations

import json
from pathlib import Path

from roco.generated import handler_indices as _hi
from roco.generated.handler_indices import H_DISPEL_MARKS, H_DISPEL_MARKS_TO_BURN
from roco.generated.weather_decoders import WEATHER_EFFECT_DECODERS


_RULES_PATH = Path(__file__).resolve().parents[2] / "compiler" / "rules" / "exact_effects.jsonl"


def _load_jsonl() -> dict[int, tuple[int, int, int, int, int, int]]:
    """Parse ``exact_effects.jsonl`` into the row-tuple shape.

    Each record carries ``effect_id``, ``handler`` (resolved against
    ``handler_indices``), an ``args`` quadruple, and an optional
    ``timing_override``.  Unknown handlers raise immediately so a
    kernel rename cannot silently drop a decoder.
    """
    out: dict[int, tuple[int, int, int, int, int, int]] = {}
    with _RULES_PATH.open("r", encoding="utf-8") as fp:
        for line_no, raw in enumerate(fp, 1):
            raw = raw.strip()
            if not raw or raw.startswith("#"):
                continue
            rec = json.loads(raw)
            handler_name = rec["handler"]
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
            timing_override = int(rec.get("timing_override", 0))
            out[int(rec["effect_id"])] = (
                handler_idx,
                int(args[0]),
                int(args[1]),
                int(args[2]),
                int(args[3]),
                timing_override,
            )
    return out


_COMPOUND: dict[int, tuple[int, int, int, int, int, int]] = {
    1042008: (H_DISPEL_MARKS, 0, 0, 0, 0, 0),
    1042014: (H_DISPEL_MARKS_TO_BURN, 5, 0, 0, 0, 0),
}


EXACT_EFFECT_DECODERS: dict[int, tuple[int, int, int, int, int, int]] = {
    **_load_jsonl(),
    **WEATHER_EFFECT_DECODERS,
    **_COMPOUND,
}


def decode_exact(effect_id: int) -> tuple[int, int, int, int, int, int] | None:
    """Return the curated row tuple for ``effect_id``, or ``None``."""
    return EXACT_EFFECT_DECODERS.get(effect_id)
