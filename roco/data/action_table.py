"""Intern linker actions into deterministic generated runtime rows."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from roco.engine.artifacts.linked_op import (
    ACTION_KIND_CONDITIONAL,
    ACTION_KIND_EXTRA_SKILL,
    ACTION_KIND_OP_LIST,
    ACTION_KIND_RANDOM,
    ACTION_KIND_TRIGGER_REGISTER,
    LinkedAction,
    LinkedOp,
)
from roco.generated.handler_order import op_index


ACTION_NONE = 0
ACTION_OP_LIST = 1
ACTION_EXTRA_SKILL = 2
ACTION_RANDOM = 3
ACTION_CONDITIONAL = 4
ACTION_TRIGGER_REGISTER = 5

KIND_TO_CODE = {
    ACTION_KIND_OP_LIST: ACTION_OP_LIST,
    ACTION_KIND_EXTRA_SKILL: ACTION_EXTRA_SKILL,
    ACTION_KIND_RANDOM: ACTION_RANDOM,
    ACTION_KIND_CONDITIONAL: ACTION_CONDITIONAL,
    ACTION_KIND_TRIGGER_REGISTER: ACTION_TRIGGER_REGISTER,
}


@dataclass
class ActionInterner:
    """Build a stable integer action table from pure linker actions."""

    _rows: list[tuple[int, tuple[Any, ...]]] = field(default_factory=lambda: [(ACTION_NONE, ())])
    _ids: dict[tuple[int, tuple[Any, ...]], int] = field(default_factory=dict)

    def intern(self, action: LinkedAction) -> int:
        row = self._lower_action(action)
        action_id = self._ids.get(row)
        if action_id is not None:
            return action_id
        action_id = len(self._rows)
        self._ids[row] = action_id
        self._rows.append(row)
        return action_id

    def rows(self) -> tuple[tuple[int, tuple[Any, ...]], ...]:
        self._validate_references()
        return tuple(self._rows)

    def _lower_action(self, action: LinkedAction) -> tuple[int, tuple[Any, ...]]:
        try:
            kind = KIND_TO_CODE[action.kind]
        except KeyError as exc:
            raise RuntimeError(f"unknown linked action kind {action.kind!r}") from exc
        if kind == ACTION_OP_LIST:
            return kind, _with_source(action, tuple(_runtime_row(op) for op in action.payload))
        if kind == ACTION_EXTRA_SKILL:
            return kind, _with_source(action, tuple(int(v) for v in action.payload))
        if kind == ACTION_RANDOM:
            count = int(action.payload[0])
            lowered: list[tuple[int, int]] = []
            for weight, child in action.payload[1]:
                lowered.append((int(weight), self.intern(child)))
            return kind, _with_source(action, (count, tuple(lowered)))
        if kind in (ACTION_CONDITIONAL, ACTION_TRIGGER_REGISTER):
            payload = tuple(
                self.intern(item) if isinstance(item, LinkedAction) else int(item)
                for item in action.payload
            )
            return kind, _with_source(action, payload)
        raise RuntimeError(f"unhandled action kind code {kind}")

    def _validate_references(self) -> None:
        max_id = len(self._rows) - 1
        for action_id, (kind, payload) in enumerate(self._rows):
            payload = _payload_body(payload)
            refs: tuple[int, ...] = ()
            if kind == ACTION_RANDOM:
                refs = tuple(int(child_id) for _weight, child_id in payload[1])
            elif kind in (ACTION_CONDITIONAL, ACTION_TRIGGER_REGISTER):
                refs = _action_refs(kind, payload)
            for child_id in refs:
                if child_id > max_id:
                    raise RuntimeError(f"action {action_id} references missing child action {child_id}")
        self._validate_acyclic()

    def _validate_acyclic(self) -> None:
        visiting: set[int] = set()
        visited: set[int] = set()

        def children(action_id: int) -> tuple[int, ...]:
            kind, payload = self._rows[action_id]
            payload = _payload_body(payload)
            if kind == ACTION_RANDOM:
                return tuple(int(child_id) for _weight, child_id in payload[1])
            if kind in (ACTION_CONDITIONAL, ACTION_TRIGGER_REGISTER):
                return _action_refs(kind, payload)
            return ()

        def visit(action_id: int) -> None:
            if action_id in visited:
                return
            if action_id in visiting:
                raise RuntimeError(f"action cycle detected at action {action_id}")
            visiting.add(action_id)
            for child_id in children(action_id):
                visit(child_id)
            visiting.remove(action_id)
            visited.add(action_id)

        for action_id in range(1, len(self._rows)):
            visit(action_id)


def _runtime_row(op: LinkedOp) -> tuple[int, int, int, int, int, int, int, int, int]:
    return (
        op_index(op.op_name),
        int(op.timing),
        int(op.target),
        0,
        0,
        int(op.p0),
        int(op.p1),
        int(op.p2),
        int(op.p3),
    )


def _with_source(action: LinkedAction, payload: tuple[Any, ...]) -> tuple[Any, ...]:
    return (
        int(action.source_ref),
        int(action.source_skill_id),
        int(action.source_buff_id),
        payload,
    )


def _payload_body(payload: tuple[Any, ...]) -> tuple[Any, ...]:
    if len(payload) == 4 and all(isinstance(value, int) for value in payload[:3]) and isinstance(payload[3], tuple):
        return payload[3]
    return payload


def _action_refs(kind: int, payload: tuple[Any, ...]) -> tuple[int, ...]:
    if kind == ACTION_CONDITIONAL and len(payload) >= 2:
        return (int(payload[-1]),)
    if kind == ACTION_TRIGGER_REGISTER and len(payload) >= 1:
        return (int(payload[-1]),)
    return ()
