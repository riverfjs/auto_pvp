from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class LinkedOp:
    op_name: str
    timing: int
    target: int
    rate: int
    p0: int = 0
    p1: int = 0
    p2: int = 0
    p3: int = 0

    def runtime_args(self) -> tuple[int, int, int, int]:
        return (self.p0, self.p1, self.p2, self.p3)


@dataclass(frozen=True)
class LinkGap:
    primitive: str
    reason: str
    source_name: str
    effect_id: int | None = None
    buff_id: int | None = None
    timing: int = 0
    target: int = 0
    rate: int = 0
    params: dict[str, Any] | None = None

    def as_record(self) -> dict[str, Any]:
        return {
            "primitive": self.primitive,
            "reason": self.reason,
            "source_name": self.source_name,
            "effect_id": self.effect_id,
            "buff_id": self.buff_id,
            "timing": self.timing,
            "target": self.target,
            "rate": self.rate,
            "params": dict(self.params or {}),
        }


class LinkGapError(RuntimeError):
    def __init__(self, gap: LinkGap):
        super().__init__(f"{gap.source_name!r} unsupported pak shape {gap.primitive!r}: {gap.reason}")
        self.gap = gap
