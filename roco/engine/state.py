"""Battle state data classes — pure data, no behavior beyond properties."""

from __future__ import annotations

from dataclasses import dataclass, field
from roco.config.constants import STARTING_ENERGY
from roco.config.status import STATUS_ELEMENT_IMMUNITY


@dataclass
class SkillRef:
    name: str
    element: str
    category: str       # 物攻 / 魔攻 / 防御 / 状态
    energy: int
    power: int
    effect: str = ""
    # Extended effect fields (populated by effect parser)
    life_drain: float = 0
    self_heal_hp: float = 0
    self_heal_energy: int = 0
    steal_energy: int = 0
    enemy_lose_energy: int = 0
    damage_reduction: float = 0
    force_switch: bool = False
    priority_mod: int = 0
    hit_count: int = 1
    leech_stacks: int = 0
    meteor_stacks: int = 0
    self_atk: float = 0
    self_spatk: float = 0
    self_def: float = 0
    self_spdef: float = 0
    self_speed: float = 0
    enemy_atk: float = 0
    enemy_def: float = 0
    enemy_spatk: float = 0
    enemy_spdef: float = 0
    enemy_speed: float = 0
    poison_stacks: int = 0
    burn_stacks: int = 0
    freeze_stacks: int = 0
    tags: list[str] = field(default_factory=list)
    # Pre-parsed effect values (set at import time, zero runtime regex)
    weather_type: str = ""           # "sandstorm"|"rain"|"snow"|""
    enemy_cost_up_amount: int = 0
    hp_cost_pct: float = 0.0
    permanent_hit_growth: int = 0
    permanent_power_growth: int = 0


@dataclass
class PetState:
    """Runtime state of a single pet during battle."""
    name: str
    base_stats: dict[str, int]
    effective_stats: dict[str, int]
    element_primary: str
    element_secondary: str = ""
    bloodline: str = ""
    nature: str = ""
    ivs: list[str] = field(default_factory=list)
    moves: list[SkillRef] = field(default_factory=list)
    current_hp: int = 0
    current_energy: int = STARTING_ENERGY
    buff_stages: dict[str, int] = field(default_factory=dict)
    status_stacks: dict[str, int] = field(default_factory=dict)
    frostbite_damage: int = 0
    power_multiplier: float = 1.0
    charging_skill_idx: int = -1
    cooldowns: dict[int, int] = field(default_factory=dict)
    is_fainted: bool = False
    leech_source: str = ""              # name of pet that applied leech
    slot: int = 0
    ability_name: str = ""
    ability_desc: str = ""
    ability_tags: list[str] = field(default_factory=list)  # pre-classified

    @property
    def max_hp(self) -> int:
        return self.effective_stats.get("hp", 1)

    @property
    def speed(self) -> int:
        return self.effective_stats.get("speed", 0)

    @property
    def hp_pct(self) -> float:
        return self.current_hp / self.max_hp if self.max_hp > 0 else 0

    @property
    def defender_types(self) -> tuple[str, ...]:
        types = [self.element_primary]
        if self.element_secondary:
            types.append(self.element_secondary)
        return tuple(types)

    def is_immune_to_status(self, status: str) -> bool:
        for elem, sname in STATUS_ELEMENT_IMMUNITY.items():
            if sname == status and elem in self.defender_types:
                return True
        return False


@dataclass
class BattleEvent:
    turn: int
    actor: str
    action: str
    detail: dict = field(default_factory=dict)


@dataclass
class MoveDecision:
    action: str
    skill_index: int | None = None
    switch_slot: int | None = None


DEFAULT_MAGIC_POWER: int = 4


@dataclass
class BattleState:
    team_a: list[PetState]
    team_b: list[PetState]
    active_a: int = 0
    active_b: int = 0
    magic_a: int = DEFAULT_MAGIC_POWER
    magic_b: int = DEFAULT_MAGIC_POWER
    weather: str | None = None
    weather_turns: int = 0
    marks_a: dict[str, float] = field(default_factory=dict)
    marks_b: dict[str, float] = field(default_factory=dict)
    turn_number: int = 0
    log: list[BattleEvent] = field(default_factory=list)
    winner: str | None = None
