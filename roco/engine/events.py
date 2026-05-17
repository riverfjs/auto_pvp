"""Fixed event table for battle stage hooks."""

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
    """Context passed to stage hooks. Hooks may modify mutable fields."""
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

    # Mutable modifiers that stage hooks can adjust
    damage_mult: float = 1.0
    heal_mult: float = 1.0
    power_mod: float = 1.0
    energy_delta: int = 0


StageHook = Callable[[EventCtx], None]
StageHookRow = tuple[int, str, StageHook]


class EventBus:
    """Priority-ordered event dispatcher. Lower priority runs first."""

    def __init__(self):
        self._stage_hooks: tuple[tuple[StageHookRow, ...], ...] = tuple(() for _ in range(_EVENT_COUNT + 1))

    def on(self, event: GameEvent, hook: StageHook,
           priority: int = 100, source: str = "unknown") -> None:
        """Register a stage hook for an event. Lower priority = earlier execution."""
        idx = event.value
        rows = tuple(sorted(self._stage_hooks[idx] + ((priority, source, hook),), key=lambda row: row[0]))
        self._stage_hooks = self._stage_hooks[:idx] + (rows,) + self._stage_hooks[idx + 1:]

    def off(self, event: GameEvent, source: str) -> None:
        """Remove all hooks from a source for an event."""
        idx = event.value
        rows = tuple(row for row in self._stage_hooks[idx] if row[1] != source)
        self._stage_hooks = self._stage_hooks[:idx] + (rows,) + self._stage_hooks[idx + 1:]

    def emit(self, ctx: EventCtx) -> EventCtx:
        """Fire all stage hooks for ctx.event in priority order. Returns modified ctx."""
        for _pri, _src, hook in self._stage_hooks[ctx.event.value]:
            if ctx.cancelled:
                break
            hook(ctx)
        return ctx

    def clear(self) -> None:
        """Remove all stage hooks."""
        self._stage_hooks = tuple(() for _ in range(_EVENT_COUNT + 1))

    def stage_hook_count(self, event: GameEvent | None = None) -> int:
        """Count registered stage hooks. If event is None, count all."""
        if event:
            return len(self._stage_hooks[event.value])
        return sum(len(rows) for rows in self._stage_hooks)
