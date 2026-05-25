from __future__ import annotations

import pytest

from roco.common.primitive_keys import buff_ref_key, effect_ref_key
from roco.compiler_v2.timing_keys import pak_cast_moment_key
from roco.data.action_table import ACTION_EXTRA_SKILL, ACTION_OP_LIST, ACTION_RANDOM, ActionInterner
from roco.engine.artifacts.linked_op import (
    ACTION_KIND_EXTRA_SKILL,
    ACTION_KIND_OP_LIST,
    ACTION_KIND_RANDOM,
    EXTRA_SKILL_POLICY_CONSERVATIVE,
    LinkGapError,
    LinkedAction,
    LinkedOp,
)
from roco.engine.artifacts.primitive_linker import link_primitive_rows
from roco.engine.kernel.flow.action_runner import drain_pending_actions
from roco.engine.kernel.flow import action_runner
from roco.engine.kernel.core.ctx import StageCtx
from roco.engine.kernel.ops.combat import op_queue_action
from roco.engine.kernel.model.state import make_state
from roco.generated.runtime.handler_order import op_index


def test_bft_freeze_links_only_canonical_shape():
    linked = link_primitive_rows(
        (buff_ref_key(20580010), pak_cast_moment_key(11), 2, 10000, 0, 0, 0, 0),
        source_name="冻结",
    )
    assert linked == (LinkedOp("op_freeze", 11, 2, 10000, 1, 0, 0, 0),)


def test_et_series_skill_links_conservative_extra_action():
    linked = link_primitive_rows(
        (effect_ref_key(1035002), pak_cast_moment_key(11), 1, 10000, 0, 0, 0, 0),
        source_name="库伦开局使用",
    )
    assert len(linked) == 1
    action = linked[0]
    assert isinstance(action, LinkedAction)
    assert action.kind == ACTION_KIND_EXTRA_SKILL
    assert action.payload == (7020530, EXTRA_SKILL_POLICY_CONSERVATIVE)


def test_et_series_unknown_policy_stays_gap():
    with pytest.raises(LinkGapError):
        link_primitive_rows(
            (effect_ref_key(1035050), pak_cast_moment_key(11), 2, 10000, 0, 0, 0, 0),
            source_name="只要你还能找到下一个倒霉蛋。",
        )


def test_et_random_links_to_pure_child_actions():
    linked = link_primitive_rows(
        (effect_ref_key(1016019), pak_cast_moment_key(11), 2, 10000, 0, 0, 0, 0),
        source_name="抓到你了",
    )
    assert len(linked) == 1
    action = linked[0]
    assert isinstance(action, LinkedAction)
    assert action.kind == ACTION_KIND_RANDOM
    count, choices = action.payload
    assert count == 2
    assert len(choices) == 2
    assert all(child.kind == ACTION_KIND_OP_LIST for _weight, child in choices)


def test_action_interner_is_deterministic_and_integer_only():
    action = LinkedAction(
        ACTION_KIND_RANDOM,
        11,
        2,
        10000,
        (
            1,
            (
                (1, LinkedAction(ACTION_KIND_EXTRA_SKILL, 11, 2, 10000, (7020530, EXTRA_SKILL_POLICY_CONSERVATIVE))),
                (1, LinkedAction(ACTION_KIND_OP_LIST, 11, 2, 10000, (LinkedOp("op_freeze", 11, 2, 10000, 1),))),
            ),
        ),
    )
    first = ActionInterner()
    second = ActionInterner()
    assert first.intern(action) == second.intern(action)
    assert first.rows() == second.rows()
    kind, payload = next(row for row in first.rows() if row[0] == ACTION_RANDOM)
    assert payload[0:3] == (0, 0, 0)
    for kind, payload in first.rows():
        assert isinstance(kind, int)
        assert _only_pure_data(payload)


def test_queue_action_does_not_drain_extra_skill_inside_effect_row(monkeypatch):
    monkeypatch.setattr(
        action_runner.catalog_actions,
        "ACTIONS",
        (
            (0, ()),
            (ACTION_EXTRA_SKILL, (7020530, EXTRA_SKILL_POLICY_CONSERVATIVE)),
        ),
    )
    state = make_state((1,), (2,))
    ctx = StageCtx()
    ctx.reset(0, 0, 1, 0, 1)
    op_queue_action(ctx, (op_index("op_queue_action"), 11, 1, 0, 0, 1, 0, 0, 0))
    assert ctx.pending_actions == (1,)
    assert ctx.extra_skill_queue == ()
    new_state = drain_pending_actions(
        state,
        ctx,
        actor_side=0,
        actor_slot=0,
        target_side=1,
        target_slot=0,
        source_skill_id=1,
        trigger_event=11,
    )
    assert new_state is state
    assert ctx.pending_actions == ()
    assert ctx.extra_skill_queue == ((7020530, EXTRA_SKILL_POLICY_CONSERVATIVE),)


def test_random_action_uses_battle_rng_and_queues_selected_child(monkeypatch):
    monkeypatch.setattr(
        action_runner.catalog_actions,
        "ACTIONS",
        (
            (0, ()),
            (ACTION_RANDOM, (1, ((1, 2),))),
            (ACTION_EXTRA_SKILL, (7020530, EXTRA_SKILL_POLICY_CONSERVATIVE)),
        ),
    )
    state = make_state((1,), (2,), rng_seed=1)
    ctx = StageCtx()
    ctx.reset(0, 0, 1, 0, 1)
    ctx.pending_actions = (1,)
    new_state = drain_pending_actions(
        state,
        ctx,
        actor_side=0,
        actor_slot=0,
        target_side=1,
        target_slot=0,
        source_skill_id=1,
        trigger_event=11,
    )
    assert new_state.rng != state.rng
    assert ctx.extra_skill_queue == ((7020530, EXTRA_SKILL_POLICY_CONSERVATIVE),)


def _only_pure_data(value) -> bool:
    if isinstance(value, int):
        return True
    if isinstance(value, tuple):
        return all(_only_pure_data(item) for item in value)
    return False
