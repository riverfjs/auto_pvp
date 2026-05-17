"""Unit tests for the event bus system."""

import pytest
from roco.engine.events import EventBus, EventCtx, GameEvent


class TestEventBus:
    def test_register_and_emit(self):
        bus = EventBus()
        called = []

        bus.on(GameEvent.TURN_START, lambda ctx: called.append("a"), priority=10)
        bus.on(GameEvent.TURN_START, lambda ctx: called.append("b"), priority=20)

        ctx = EventCtx(GameEvent.TURN_START, state=None)
        bus.emit(ctx)
        assert called == ["a", "b"]  # lower priority first

    def test_priority_order(self):
        bus = EventBus()
        order = []

        bus.on(GameEvent.AFTER_DAMAGE, lambda c: order.append(3), priority=80, source="skill")
        bus.on(GameEvent.AFTER_DAMAGE, lambda c: order.append(1), priority=10, source="mark")
        bus.on(GameEvent.AFTER_DAMAGE, lambda c: order.append(2), priority=50, source="ability")

        bus.emit(EventCtx(GameEvent.AFTER_DAMAGE, state=None))
        assert order == [1, 2, 3]

    def test_cancellation_stops_chain(self):
        bus = EventBus()
        called = []

        def canceller(ctx):
            ctx.cancelled = True
            called.append("cancel")

        bus.on(GameEvent.BEFORE_MOVE, canceller, priority=10, source="counter")
        bus.on(GameEvent.BEFORE_MOVE, lambda c: called.append("should_not_run"), priority=20)

        bus.emit(EventCtx(GameEvent.BEFORE_MOVE, state=None))
        assert called == ["cancel"]

    def test_stage_hook_modifies_context(self):
        bus = EventBus()

        def doubler(ctx):
            ctx.damage_mult *= 2.0

        def add_bonus(ctx):
            ctx.power_mod += 0.3

        bus.on(GameEvent.AFTER_DAMAGE, doubler, priority=10, source="weather")
        bus.on(GameEvent.AFTER_DAMAGE, add_bonus, priority=20, source="marks")

        ctx = EventCtx(GameEvent.AFTER_DAMAGE, state=None)
        result = bus.emit(ctx)
        assert result.damage_mult == 2.0
        assert result.power_mod == 1.3

    def test_off_removes_by_source(self):
        bus = EventBus()
        called = []

        bus.on(GameEvent.TURN_END, lambda c: called.append("keep"), priority=10, source="marks")
        bus.on(GameEvent.TURN_END, lambda c: called.append("remove"), priority=20, source="debug")

        bus.off(GameEvent.TURN_END, "debug")
        bus.emit(EventCtx(GameEvent.TURN_END, state=None))
        assert called == ["keep"]

    def test_clear_all(self):
        bus = EventBus()
        bus.on(GameEvent.TURN_START, lambda c: None, source="a")
        bus.on(GameEvent.TURN_END, lambda c: None, source="b")
        assert bus.stage_hook_count() == 2
        bus.clear()
        assert bus.stage_hook_count() == 0

    def test_different_events_independent(self):
        bus = EventBus()
        a_calls = []
        b_calls = []

        bus.on(GameEvent.TURN_START, lambda c: a_calls.append(1))
        bus.on(GameEvent.TURN_END, lambda c: b_calls.append(1))

        bus.emit(EventCtx(GameEvent.TURN_START, state=None))
        assert a_calls == [1]
        assert b_calls == []

    def test_stage_hook_count(self):
        bus = EventBus()
        bus.on(GameEvent.TURN_START, lambda c: None, source="a")
        bus.on(GameEvent.TURN_START, lambda c: None, source="b")
        bus.on(GameEvent.TURN_END, lambda c: None, source="c")

        assert bus.stage_hook_count(GameEvent.TURN_START) == 2
        assert bus.stage_hook_count(GameEvent.TURN_END) == 1
        assert bus.stage_hook_count() == 3

    def test_event_ctx_defaults(self):
        ctx = EventCtx(GameEvent.TURN_START, state=None)
        assert ctx.actor is None
        assert ctx.target is None
        assert ctx.cancelled is False
        assert ctx.damage_mult == 1.0
        assert ctx.heal_mult == 1.0
        assert ctx.power_mod == 1.0
        assert ctx.energy_delta == 0

    def test_stage_hooks_are_stored_as_fixed_event_table(self):
        bus = EventBus()
        bus.on(GameEvent.TURN_START, lambda c: None, source="a")
        assert isinstance(bus._stage_hooks, tuple)
        assert isinstance(bus._stage_hooks[GameEvent.TURN_START.value], tuple)

    def test_multiple_emit_same_context(self):
        bus = EventBus()
        count = [0]

        def counter(ctx):
            count[0] += 1

        bus.on(GameEvent.TURN_START, counter, source="a")
        bus.emit(EventCtx(GameEvent.TURN_START, state=None))
        bus.emit(EventCtx(GameEvent.TURN_START, state=None))
        assert count[0] == 2
