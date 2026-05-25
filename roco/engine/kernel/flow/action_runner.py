"""Runtime execution for generated action rows.

Actions are generated as pure integer/tuple data.  This module owns the
stateful interpretation: RNG, queueing forced extra skills, and bounded child
execution.  It deliberately does not run the extra-skill queue from inside an
effect row; mechanics drains that queue only after the current skill core
resolution has completed.
"""

from __future__ import annotations

from roco.engine.common.rng import next_rng
from roco.engine.kernel.core.ctx import StageCtx
from roco.engine.kernel.core.dispatch import HANDLERS, HANDLER_COUNT
from roco.engine.kernel.core.rows import ROW_TAG
from roco.engine.kernel.model.state import KernelState
from roco.engine.artifacts.linked_op import EXTRA_SKILL_POLICY_CONSERVATIVE
from roco.generated.catalog import actions as catalog_actions


MAX_ACTION_DEPTH = 8


ACTION_OP_LIST = 1
ACTION_EXTRA_SKILL = 2
ACTION_RANDOM = 3
ACTION_CONDITIONAL = 4
ACTION_TRIGGER_REGISTER = 5

def drain_pending_actions(
    state: KernelState,
    ctx: StageCtx,
    *,
    actor_side: int,
    actor_slot: int,
    target_side: int,
    target_slot: int,
    source_skill_id: int,
    trigger_event: int,
    action_flags: int = 0,
    allow_extra_queue: bool = True,
    depth: int = 0,
) -> KernelState:
    """Execute queued non-extra actions in stable FIFO order."""

    pending = tuple(ctx.pending_actions)
    ctx.pending_actions = ()
    for action_id in pending:
        state = execute_action(
            state,
            ctx,
            int(action_id),
            actor_side=actor_side,
            actor_slot=actor_slot,
            target_side=target_side,
            target_slot=target_slot,
            source_ref=0,
            source_skill_id=source_skill_id,
            source_buff_id=0,
            source_instance_id=0,
            trigger_event=trigger_event,
            action_flags=action_flags,
            allow_extra_queue=allow_extra_queue,
            depth=depth,
        )
    return state


def execute_action(
    state: KernelState,
    ctx: StageCtx,
    action_id: int,
    *,
    actor_side: int,
    actor_slot: int,
    target_side: int,
    target_slot: int,
    source_ref: int,
    source_skill_id: int,
    source_buff_id: int,
    source_instance_id: int,
    trigger_event: int,
    action_flags: int,
    allow_extra_queue: bool,
    depth: int,
) -> KernelState:
    del actor_side, actor_slot, target_side, target_slot
    del source_instance_id
    del trigger_event, action_flags
    if depth > MAX_ACTION_DEPTH:
        raise RuntimeError(f"action depth exceeded {MAX_ACTION_DEPTH}")
    if action_id <= 0 or action_id >= len(catalog_actions.ACTIONS):
        raise RuntimeError(f"unknown action_id {action_id}")
    kind, payload = catalog_actions.ACTIONS[action_id]
    source_ref, source_skill_id, source_buff_id, payload = _split_source_payload(
        payload,
        fallback_source_ref=source_ref,
        fallback_source_skill_id=source_skill_id,
        fallback_source_buff_id=source_buff_id,
    )
    if kind == ACTION_OP_LIST:
        _execute_op_rows(ctx, payload)
        return state
    if kind == ACTION_EXTRA_SKILL:
        if not allow_extra_queue:
            raise RuntimeError("extra skill action attempted inside a non-queueable action context")
        skill_id = int(payload[0])
        policy = int(payload[1])
        if policy != EXTRA_SKILL_POLICY_CONSERVATIVE:
            raise RuntimeError(f"unsupported extra skill policy {policy}")
        ctx.extra_skill_queue = tuple(ctx.extra_skill_queue) + ((skill_id, policy),)
        return state
    if kind == ACTION_RANDOM:
        return _execute_random_action(
            state,
            ctx,
            payload,
            source_ref=source_ref,
            source_skill_id=source_skill_id,
            source_buff_id=source_buff_id,
            allow_extra_queue=allow_extra_queue,
            depth=depth,
        )
    if kind in (ACTION_CONDITIONAL, ACTION_TRIGGER_REGISTER):
        raise RuntimeError(f"runtime action kind {kind} is not implemented in this batch")
    raise RuntimeError(f"unknown runtime action kind {kind}")


def _execute_op_rows(ctx: StageCtx, rows: tuple[tuple[int, ...], ...]) -> None:
    for row in rows:
        handler_idx = row[ROW_TAG]
        if 0 < handler_idx < HANDLER_COUNT:
            HANDLERS[handler_idx](ctx, row)


def _execute_random_action(
    state: KernelState,
    ctx: StageCtx,
    payload: tuple,
    *,
    source_ref: int,
    source_skill_id: int,
    source_buff_id: int,
    allow_extra_queue: bool,
    depth: int,
) -> KernelState:
    count = int(payload[0])
    choices = tuple(payload[1])
    if count <= 0:
        raise RuntimeError(f"random action has invalid draw count {count}")
    total = sum(max(0, int(weight)) for weight, _child_id in choices)
    if total <= 0:
        raise RuntimeError("random action has no positive weights")
    for _ in range(count):
        rng = next_rng(state.rng)
        pick = rng % total
        state = state._replace(rng=rng)
        acc = 0
        selected = 0
        for weight, child_id in choices:
            acc += max(0, int(weight))
            if pick < acc:
                selected = int(child_id)
                break
        if selected <= 0:
            raise RuntimeError("random action failed to select a child action")
        state = execute_action(
            state,
            ctx,
            selected,
            actor_side=ctx.actor_side,
            actor_slot=ctx.actor_slot,
            target_side=ctx.target_side,
            target_slot=ctx.target_slot,
            source_ref=source_ref,
            source_skill_id=source_skill_id or ctx.skill_id,
            source_buff_id=source_buff_id,
            source_instance_id=0,
            trigger_event=0,
            action_flags=0,
            allow_extra_queue=allow_extra_queue,
            depth=depth + 1,
        )
    return state


def _split_source_payload(
    payload: tuple,
    *,
    fallback_source_ref: int,
    fallback_source_skill_id: int,
    fallback_source_buff_id: int,
) -> tuple[int, int, int, tuple]:
    if (
        len(payload) == 4
        and all(isinstance(value, int) for value in payload[:3])
        and isinstance(payload[3], tuple)
    ):
        source_ref = int(payload[0]) or fallback_source_ref
        source_skill_id = int(payload[1]) or fallback_source_skill_id
        source_buff_id = int(payload[2]) or fallback_source_buff_id
        return source_ref, source_skill_id, source_buff_id, payload[3]
    return fallback_source_ref, fallback_source_skill_id, fallback_source_buff_id, payload
