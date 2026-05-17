"""Data-driven ability runtime.

Abilities are compiled into `ability_effects` rows during import. Runtime code
only dispatches those rows by timing; it does not special-case ability names.
"""

from __future__ import annotations

from roco.engine.effect_exec import run_ability_effects
from roco.engine.effect_model import Timing
from roco.engine.events import GameEvent


_TIMING_COUNT = max(timing.value for timing in Timing) + 1
_EVENT_ROWS: tuple[tuple[Timing, GameEvent], ...] = (
    (Timing.PASSIVE, GameEvent.PASSIVE),
    (Timing.BATTLE_START, GameEvent.BATTLE_START),
    (Timing.TURN_START, GameEvent.TURN_START),
    (Timing.BEFORE_MOVE, GameEvent.BEFORE_MOVE),
    (Timing.CHECK_HIT, GameEvent.CHECK_HIT),
    (Timing.CALC_DAMAGE, GameEvent.CALC_DAMAGE),
    (Timing.ADJUST_DAMAGE, GameEvent.ADJUST_DAMAGE),
    (Timing.APPLY_DAMAGE, GameEvent.APPLY_DAMAGE),
    (Timing.TAKE_DAMAGE, GameEvent.TAKE_DAMAGE),
    (Timing.AFTER_MOVE, GameEvent.AFTER_MOVE),
    (Timing.TURN_END, GameEvent.TURN_END),
    (Timing.SWITCH_IN, GameEvent.SWITCH_IN),
    (Timing.SWITCH_OUT, GameEvent.SWITCH_OUT),
    (Timing.ENEMY_SWITCH, GameEvent.ENEMY_SWITCH),
    (Timing.FAINT, GameEvent.FAINT),
    (Timing.BE_KILLED, GameEvent.BE_KILLED),
    (Timing.KILL, GameEvent.KILL),
    (Timing.COUNTER_SUCCESS, GameEvent.COUNTER_SUCCESS),
    (Timing.ALLY_COUNTER, GameEvent.ALLY_COUNTER),
)
_EVENT_TABLE_MUT: list[GameEvent | None] = [None] * _TIMING_COUNT
for _timing, _event in _EVENT_ROWS:
    _EVENT_TABLE_MUT[_timing.value] = _event
TIMING_EVENT_TABLE: tuple[GameEvent | None, ...] = tuple(_EVENT_TABLE_MUT)

ACTOR_SCOPED_MASK = sum(1 << timing.value for timing in (
    Timing.BEFORE_MOVE,
    Timing.CHECK_HIT,
    Timing.CALC_DAMAGE,
    Timing.ADJUST_DAMAGE,
    Timing.APPLY_DAMAGE,
    Timing.TAKE_DAMAGE,
    Timing.AFTER_MOVE,
    Timing.SWITCH_IN,
    Timing.SWITCH_OUT,
    Timing.ENEMY_SWITCH,
    Timing.FAINT,
    Timing.BE_KILLED,
    Timing.KILL,
    Timing.COUNTER_SUCCESS,
    Timing.ALLY_COUNTER,
))


def register_ability_handlers(bus, pet) -> None:
    if not pet.persistent.ability_effects:
        return
    timings = tuple(sorted({item.effect.timing for item in pet.persistent.ability_effects}, key=int))
    for timing in timings:
        event = TIMING_EVENT_TABLE[timing.value] if timing.value < len(TIMING_EVENT_TABLE) else None
        if event is None:
            continue

        def handler(ctx, pet=pet, timing=timing):
            if ACTOR_SCOPED_MASK & (1 << timing.value) and ctx.actor is not pet:
                return
            run_ability_effects(ctx, pet, timing)

        bus.on(event, handler, priority=100, source=f"ability:{pet.persistent.ability_id}:{timing.name}")
