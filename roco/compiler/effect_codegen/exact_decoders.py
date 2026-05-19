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
    H_HIT_COUNT_DELTA,
    H_SET_SELF_COOLDOWN,
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
    # "防御类技能公共冷却 1/2" — 3-turn cooldown on the actor's own skill
    # slot, attached to defensive skills (防御 / 有效预防 / 风墙 / 听桥 /
    # 截拳 / …).  Top strict-build blocker by used_count (1037002 alone
    # appears on 42 used skills, 773 references).  The two pak variants
    # share semantics; they just live in different cooldown groups in
    # pak's bookkeeping which the kernel does not distinguish.
    1037001: (H_SET_SELF_COOLDOWN, 3, 0, 0, 0, 0),
    1037002: (H_SET_SELF_COOLDOWN, 3, 0, 0, 0, 0),
    # "连击N" — each pak id adds N hits to the actor's attack at
    # CALC_DAMAGE; target=self triggers the additive branch of
    # ``op_hit_count_delta``.  Editor names like "连击10" actually mean
    # variant index, not stack count — the per-id ``effect_param[0]`` is
    # the real delta.  9 distinct skills use 1032002 (+2 hits) most.
    1032001: (H_HIT_COUNT_DELTA, 1, 0, 0, 0, 0),
    1032002: (H_HIT_COUNT_DELTA, 2, 0, 0, 0, 0),
    1032003: (H_HIT_COUNT_DELTA, 3, 0, 0, 0, 0),
    1032004: (H_HIT_COUNT_DELTA, 4, 0, 0, 0, 0),
    1032005: (H_HIT_COUNT_DELTA, 5, 0, 0, 0, 0),
    1032006: (H_HIT_COUNT_DELTA, 6, 0, 0, 0, 0),
    1032007: (H_HIT_COUNT_DELTA, 7, 0, 0, 0, 0),
    1032008: (H_HIT_COUNT_DELTA, 8, 0, 0, 0, 0),
    1032009: (H_HIT_COUNT_DELTA, 9, 0, 0, 0, 0),
    1032010: (H_HIT_COUNT_DELTA, 10, 0, 0, 0, 0),
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
