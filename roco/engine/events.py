"""Unified event bus for battle hook system.

All game subsystems (weather, marks, skills, abilities, status) register
handlers on the EventBus. The BattleEngine only emits events — it never
calls subsystems directly.

Design:
  - GameEvent: enum of all hook points
  - EventCtx: data passed to handlers, with mutable modifier fields
  - EventBus: registration + ordered dispatch

Usage:
  bus = EventBus()
  bus.on(GameEvent.AFTER_DAMAGE, my_handler, priority=50, source="skill")
  ctx = bus.emit(EventCtx(GameEvent.AFTER_DAMAGE, state, actor=attacker))
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from roco.engine.state import ActivePet, BattleState


class GameEvent(Enum):
    """All hook points in the battle lifecycle."""

    # ── Round-level ──
    BATTLE_START = auto()      # battle begins (after all pets initialized)
    TURN_START = auto()        # start of turn, before energy gain
    TURN_END = auto()          # end of turn, after status/weather ticks

    # ── Move pipeline (engine-inspired explicit steps) ──
    BEFORE_MOVE = auto()       # setup: charge, energy mod, defense (can cancel)
    CHECK_HIT = auto()         # accuracy/immune check
    CALC_DAMAGE = auto()       # compute raw damage
    ADJUST_DAMAGE = auto()     # modify damage (defense reduction, barrel, etc.)
    APPLY_DAMAGE = auto()      # apply to HP
    AFTER_MOVE = auto()        # post-move effects: drain, status, stat change, weather
    # Aliases for backward compat
    PRE_USE = BEFORE_MOVE
    AFTER_DAMAGE = APPLY_DAMAGE
    ON_DAMAGE = APPLY_DAMAGE
    POST_USE = AFTER_MOVE
    MOVE_MISS = auto()
    CHARGE_START = auto()

    # ── Pet lifecycle ──
    SWITCH_IN = auto()         # pet enters battle
    SWITCH_OUT = auto()        # pet leaves battle
    ENEMY_SWITCH = auto()      # opponent switches
    FAINT = auto()             # pet faints
    BE_KILLED = auto()         # pet is killed by opponent
    KILL = auto()              # pet kills an opponent
    PASSIVE = auto()           # always-on passive check

    # ── Interaction ──
    COUNTER_SUCCESS = auto()   # counter move succeeds (应对成功)
    ALLY_COUNTER = auto()      # ally on the team successfully countered
    TAKE_DAMAGE = auto()       # pet takes damage (after HP deducted)
    STATUS_APPLIED = auto()    # status effect applied to pet
    STATUS_TICK = auto()       # per-pet status tick at turn end
    BUFF_CHANGED = auto()      # buff/debuff stage changed
    HEAL = auto()              # HP healed
    ENERGY_CHANGE = auto()     # energy gained or lost
    WEATHER_CHANGE = auto()    # weather set or cleared


@dataclass
class EventCtx:
    """Context passed to event handlers. Handlers may modify mutable fields."""
    event: GameEvent
    state: "BattleState"
    actor: "ActivePet | None" = None
    target: "ActivePet | None" = None
    data: dict = field(default_factory=dict)
    cancelled: bool = False

    # Mutable modifiers that handlers can adjust
    damage_mult: float = 1.0
    heal_mult: float = 1.0
    power_mod: float = 1.0
    energy_delta: int = 0


# Handler: (EventCtx) -> None
EventHandler = Callable[[EventCtx], None]


class EventBus:
    """Priority-ordered event dispatcher. Lower priority runs first."""

    def __init__(self):
        self._handlers: dict[GameEvent, list[tuple[int, str, EventHandler]]] = {}

    def on(self, event: GameEvent, handler: EventHandler,
           priority: int = 100, source: str = "unknown") -> None:
        """Register a handler for an event. Lower priority = earlier execution."""
        self._handlers.setdefault(event, []).append((priority, source, handler))
        self._handlers[event].sort(key=lambda x: x[0])

    def off(self, event: GameEvent, source: str) -> None:
        """Remove all handlers from a source for an event."""
        if event not in self._handlers:
            return
        self._handlers[event] = [
            (p, s, h) for p, s, h in self._handlers[event] if s != source
        ]

    def emit(self, ctx: EventCtx) -> EventCtx:
        """Fire all handlers for ctx.event in priority order. Returns modified ctx."""
        for _pri, src, handler in self._handlers.get(ctx.event, []):
            if ctx.cancelled:
                break
            handler(ctx)
        return ctx

    def clear(self) -> None:
        """Remove all handlers."""
        self._handlers.clear()

    def handler_count(self, event: GameEvent | None = None) -> int:
        """Count registered handlers. If event is None, count all."""
        if event:
            return len(self._handlers.get(event, []))
        return sum(len(v) for v in self._handlers.values())
