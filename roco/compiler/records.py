"""Import-time static Pet and skill definitions.

Battle state for the fixed engine lives in ``roco.engine.kernel.state``. This
module is kept small for parsers, classifiers, and SQLite catalog inspection.
"""

from __future__ import annotations

from dataclasses import dataclass

from roco.compiler.effect_model import EffectFlag, SkillEffect
from roco.common.enums import SkillCategory, Stats


@dataclass(slots=True)
class SkillData:
    """Static skill definition loaded from canonical data."""

    name: str
    element: str
    category: SkillCategory
    energy: int
    power: int
    effect: str
    skill_id: int = 0
    element_id: int = 0
    effect_flags: int = EffectFlag.NONE
    effects: tuple[SkillEffect, ...] = ()
    hit_count: int = 1
    priority_mod: int = 0


@dataclass(slots=True)
class PetData:
    """Static Pet definition compiled from the normalized data store."""

    pet_id: int
    name: str
    stats: tuple[int, int, int, int, int, int]
    types: tuple[str, str]
    skill_ids: tuple[int, ...] = ()
    ability_id: int = 0
    ability_name: str = ""
    ability_desc: str = ""

    def stat(self, stat: Stats) -> int:
        return self.stats[stat.value]
