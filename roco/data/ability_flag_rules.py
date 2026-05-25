from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AbilityFlagRule:
    effect_id: int
    flag_name: str
