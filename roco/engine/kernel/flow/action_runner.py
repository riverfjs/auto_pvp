"""Runtime execution for generated action rows.

Actions are generated as pure integer/tuple data.  This module owns the
stateful interpretation: RNG, queueing forced extra skills, and bounded child
execution.  It deliberately does not run the extra-skill queue from inside an
effect row; mechanics drains that queue only after the current skill core
resolution has completed.
"""

from __future__ import annotations

from roco.common.enums import StatusType
from roco.common.packing import MarkIdx, _unpack_mark
from roco.engine.common.rng import next_rng
from roco.engine.artifacts.action_payloads import (
    COND_KIND_ACTIVE_BUFF,
    COND_KIND_CUTE,
    COND_KIND_MARK,
    COND_KIND_STATUS,
    COND_REF_COUNT_AT_LEAST,
    COND_SCOPE_ENEMY,
    COND_SCOPE_SELF,
    TRIGGER_AFTER_SKILL,
)
from roco.engine.artifacts.linked_op import EXTRA_SKILL_POLICY_CONSERVATIVE
from roco.engine.kernel.core.ctx import StageCtx
from roco.engine.kernel.core.dispatch import HANDLERS, HANDLER_COUNT
from roco.engine.kernel.core.rows import ROW_HANDLER_IDX, TARGET_ENEMY, TARGET_SELF
from roco.engine.kernel.model.active_buffs import active_buff_id, iter_active_buffs
from roco.engine.kernel.model.state import KernelState, side, status_stack
from roco.engine.kernel.ops.buffs import op_apply_active_buff
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
    del source_instance_id
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
            actor_side=actor_side,
            actor_slot=actor_slot,
            target_side=target_side,
            target_slot=target_slot,
            source_ref=source_ref,
            source_skill_id=source_skill_id,
            source_buff_id=source_buff_id,
            trigger_event=trigger_event,
            action_flags=action_flags,
            allow_extra_queue=allow_extra_queue,
            depth=depth,
        )
    if kind == ACTION_CONDITIONAL:
        return _execute_conditional_action(
            state,
            ctx,
            payload,
            actor_side=actor_side,
            actor_slot=actor_slot,
            target_side=target_side,
            target_slot=target_slot,
            source_ref=source_ref,
            source_skill_id=source_skill_id,
            source_buff_id=source_buff_id,
            trigger_event=trigger_event,
            action_flags=action_flags,
            allow_extra_queue=allow_extra_queue,
            depth=depth,
        )
    if kind == ACTION_TRIGGER_REGISTER:
        _execute_trigger_register(ctx, payload)
        return state
    raise RuntimeError(f"unknown runtime action kind {kind}")


def _execute_op_rows(ctx: StageCtx, rows: tuple[tuple[int, ...], ...]) -> None:
    for row in rows:
        handler_idx = row[ROW_HANDLER_IDX]
        if 0 < handler_idx < HANDLER_COUNT:
            HANDLERS[handler_idx](ctx, row)


def _execute_random_action(
    state: KernelState,
    ctx: StageCtx,
    payload: tuple,
    *,
    actor_side: int,
    actor_slot: int,
    target_side: int,
    target_slot: int,
    source_ref: int,
    source_skill_id: int,
    source_buff_id: int,
    trigger_event: int,
    action_flags: int,
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
            actor_side=actor_side,
            actor_slot=actor_slot,
            target_side=target_side,
            target_slot=target_slot,
            source_ref=source_ref,
            source_skill_id=source_skill_id or ctx.skill_id,
            source_buff_id=source_buff_id,
            source_instance_id=0,
            trigger_event=trigger_event,
            action_flags=action_flags,
            allow_extra_queue=allow_extra_queue,
            depth=depth + 1,
        )
    return state


def _execute_conditional_action(
    state: KernelState,
    ctx: StageCtx,
    payload: tuple,
    *,
    actor_side: int,
    actor_slot: int,
    target_side: int,
    target_slot: int,
    source_ref: int,
    source_skill_id: int,
    source_buff_id: int,
    trigger_event: int,
    action_flags: int,
    allow_extra_queue: bool,
    depth: int,
) -> KernelState:
    if len(payload) != 4:
        raise RuntimeError(f"conditional action has malformed payload {payload!r}")
    condition_kind = int(payload[0])
    if condition_kind != COND_REF_COUNT_AT_LEAST:
        raise RuntimeError(f"unsupported condition kind {condition_kind}")
    specs = tuple(payload[1])
    threshold = int(payload[2])
    child_id = int(payload[3])
    if _condition_count(state, specs, actor_side, actor_slot, target_side, target_slot) < threshold:
        return state
    return execute_action(
        state,
        ctx,
        child_id,
        actor_side=actor_side,
        actor_slot=actor_slot,
        target_side=target_side,
        target_slot=target_slot,
        source_ref=source_ref,
        source_skill_id=source_skill_id or ctx.skill_id,
        source_buff_id=source_buff_id,
        source_instance_id=0,
        trigger_event=trigger_event,
        action_flags=action_flags,
        allow_extra_queue=allow_extra_queue,
        depth=depth + 1,
    )


def _condition_count(
    state: KernelState,
    specs: tuple,
    actor_side: int,
    actor_slot: int,
    target_side: int,
    target_slot: int,
) -> int:
    total = 0
    for raw_spec in specs:
        kind, value, scope = (int(raw_spec[0]), int(raw_spec[1]), int(raw_spec[2]))
        side_id, slot = (actor_side, actor_slot) if scope == COND_SCOPE_SELF else (target_side, target_slot)
        if scope not in (COND_SCOPE_SELF, COND_SCOPE_ENEMY):
            raise RuntimeError(f"unsupported condition scope {scope}")
        side_state = side(state, side_id)
        pet = side_state.pets[slot]
        if kind == COND_KIND_STATUS:
            total += status_stack(pet, StatusType(value))
            continue
        if kind == COND_KIND_MARK:
            total += _unpack_mark(side_state.marks, MarkIdx(value))
            continue
        if kind == COND_KIND_ACTIVE_BUFF:
            total += sum(1 for _idx, lane in iter_active_buffs(pet.active_buffs) if active_buff_id(lane) == value)
            continue
        if kind == COND_KIND_CUTE:
            total += pet.cute
            continue
        raise RuntimeError(f"unsupported condition spec kind {kind}")
    return total


def _execute_trigger_register(ctx: StageCtx, payload: tuple) -> None:
    if len(payload) != 6:
        raise RuntimeError(f"trigger_register action has malformed payload {payload!r}")
    trigger_kind, target, buff_id, reduce_type, p0, p1 = (int(value) for value in payload)
    if trigger_kind != TRIGGER_AFTER_SKILL:
        raise RuntimeError(f"unsupported trigger_register kind {trigger_kind}")
    if target not in (TARGET_SELF, TARGET_ENEMY):
        raise RuntimeError(f"trigger_register has unsupported target {target}")
    op_apply_active_buff(
        ctx,
        (0, 0, target, 0, 0, buff_id, reduce_type, p0, p1),
    )


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
