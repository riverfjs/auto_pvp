"""Hand-curated exact ``effect_id`` → kernel row table.

Pak ``EFFECT_CONF`` rows fall into three buckets:

* ``type=2`` damage rows decode structurally from ``effect_param`` —
  done in :func:`classify.decode_effect`.
* ``type=1`` rows with exactly one buff_id in their ``effect_param``
  collapse to "apply that buff" deterministically — also handled
  structurally.
* Anything else (``type=1`` compound payloads with marker + apply-buff
  slots, ``type=3`` state changes, weather setters, dispel chains, …)
  needs human inspection of the pak record to map to a kernel
  primitive.  Those land here.

Every entry MUST cite the pak record's ``editor_name`` and the in-game
skill that uses it so future readers can re-verify against pak.  The
row shape is the same as a normal effect row plus a ``timing_override``:
``(handler_idx, p0, p1, p2, p3, timing_override)``.  ``timing_override``
of zero keeps the skill_result's own ``cast_moment``; any non-zero
value pins the row to that timing.

To add an entry: read the pak ``EFFECT_CONF`` record, decide which
kernel handler models its semantics, and add the tuple here.  Anything
not in this table that the structural decoders cannot classify shows up
as an :mod:`.audit` gap so coverage is honest by default.
"""

from __future__ import annotations

from roco.common.enums import WeatherType
from roco.generated.handler_indices import (
    H_DISPEL_MARKS,
    H_DISPEL_MARKS_TO_BURN,
    H_WEATHER,
)


# ``timing_override = 0`` → use the skill_result's own cast_moment.
# Non-zero overrides exist for legacy effects whose pak timing predates
# the kernel feature that processes them; they should shrink over time.
EXACT_EFFECT_DECODERS: dict[int, tuple[int, int, int, int, int, int]] = {
    # Weather setters — pak ``type=3`` with ``effect_param[0]`` carrying a
    # pak-internal weather code; map to the kernel's WeatherType enum and
    # seed an 8-turn duration so the first end-turn tick lands the
    # 7-turn-remaining expectation that the kernel tests assert.
    1028001: (H_WEATHER, WeatherType.RAIN.value,      8, 0, 0, 0),  # 求雨
    1028003: (H_WEATHER, WeatherType.SANDSTORM.value, 8, 0, 0, 0),  # 沙暴
    1028004: (H_WEATHER, WeatherType.NONE.value,      0, 0, 0, 0),  # 晴天 (clear weather)
    1028005: (H_WEATHER, WeatherType.SNOW.value,      8, 0, 0, 0),  # 暴风雪
    # 场地转换标记 — pak crams two dozen mark buff_ids into one
    # ``effect_param`` slot to signal "dispel all marks on both sides",
    # not "apply wind/water/...".  Maps to the existing dispel-all-marks
    # kernel primitive.
    1042008: (H_DISPEL_MARKS, 0, 0, 0, 0, 0),
    # 标记转换灼烧 — skill text: "dispel both sides' marks, every dispelled
    # stack gives the enemy 5 burn".  The dispel half is 1042008 above and
    # runs at CALC_DAMAGE; this row fires at TURN_END (pak ``cast_moment=12``)
    # and reads the turn's running dispel tally off ``ctx.marks_dispelled``
    # to scale the burn it applies.
    1042014: (H_DISPEL_MARKS_TO_BURN, 5, 0, 0, 0, 0),
}


def decode_exact(effect_id: int) -> tuple[int, int, int, int, int, int] | None:
    """Return the row tuple for ``effect_id`` if it has a curated entry."""
    return EXACT_EFFECT_DECODERS.get(effect_id)
