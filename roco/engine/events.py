"""Fixed event table for the battle hook system."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum, auto
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from roco.engine.state import ActivePet, BattleState, SkillData


class GameEvent(IntEnum):
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


_EVENT_COUNT = max(event.value for event in GameEvent)


@dataclass(slots=True)
class EventCtx:
    """Context passed to event handlers. Handlers may modify mutable fields."""
    event: GameEvent
    state: "BattleState | None"
    actor: "ActivePet | None" = None
    target: "ActivePet | None" = None
    skill: "SkillData | None" = None
    skill_index: int = -1
    team: str = ""
    cost: int = 0
    damage: int = 0
    countered: bool = False
    first_strike: bool = False
    barrel: bool = False
    burst_cost_up: int = 0
    burst_element_reduce: str = ""
    power_bonus: int = 0
    hit_count_delta: int = 0
    hit_count_mult: float = 1.0
    cancelled: bool = False

    # Mutable modifiers that handlers can adjust
    damage_mult: float = 1.0
    heal_mult: float = 1.0
    power_mod: float = 1.0
    energy_delta: int = 0


# Handler: (EventCtx) -> None
EventHandler = Callable[[EventCtx], None]
HandlerRow = tuple[int, str, EventHandler]


class EventBus:
    """Priority-ordered event dispatcher. Lower priority runs first."""

    def __init__(self):
        self._handlers: tuple[tuple[HandlerRow, ...], ...] = tuple(() for _ in range(_EVENT_COUNT + 1))

    def on(self, event: GameEvent, handler: EventHandler,
           priority: int = 100, source: str = "unknown") -> None:
        """Register a handler for an event. Lower priority = earlier execution."""
        idx = event.value
        rows = tuple(sorted(self._handlers[idx] + ((priority, source, handler),), key=lambda row: row[0]))
        self._handlers = self._handlers[:idx] + (rows,) + self._handlers[idx + 1:]

    def off(self, event: GameEvent, source: str) -> None:
        """Remove all handlers from a source for an event."""
        idx = event.value
        rows = tuple(row for row in self._handlers[idx] if row[1] != source)
        self._handlers = self._handlers[:idx] + (rows,) + self._handlers[idx + 1:]

    def emit(self, ctx: EventCtx) -> EventCtx:
        """Fire all handlers for ctx.event in priority order. Returns modified ctx."""
        for _pri, _src, handler in self._handlers[ctx.event.value]:
            if ctx.cancelled:
                break
            handler(ctx)
        return ctx

    def clear(self) -> None:
        """Remove all handlers."""
        self._handlers = tuple(() for _ in range(_EVENT_COUNT + 1))

    def handler_count(self, event: GameEvent | None = None) -> int:
        """Count registered handlers. If event is None, count all."""
        if event:
            return len(self._handlers[event.value])
        return sum(len(rows) for rows in self._handlers)
