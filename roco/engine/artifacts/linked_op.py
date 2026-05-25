from __future__ import annotations

from dataclasses import dataclass


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
