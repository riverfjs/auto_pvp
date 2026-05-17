"""Runtime Pet state: two-tier definitions plus active packed state."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from roco.engine.effect_model import (
    AbilityEffect,
    EffectFlag,
    EffectSpec,
    EffectTag,
    SkillEffect,
    Timing,
)
from roco.engine.enums import (
    AbilityFlag,
    Element,
    ELEMENT_NAMES,
    SkillCategory,
    Stats,
    StatusFlag,
    StatusType,
    WeatherType,
    normalize_element_name,
)
from roco.engine.packing import (
    DevotionIdx,
    MarkIdx,
    _cooldown_at,
    _inc_skill_count,
    _pack_buff,
    _pack_burst_entries,
    _pack_devotion,
    _pack_marks,
    _pack_skill_counts,
    _pack_status,
    _pack_weather,
    _set_buff,
    _set_burst_entry,
    _set_cooldown,
    _set_mark,
    _set_status,
    _tick_cooldowns,
    _unpack_buff,
    _unpack_burst_entry,
    _unpack_devotion,
    _unpack_mark,
    _unpack_skill_count,
    _unpack_status,
    _unpack_weather,
    buff_multiplier,
)

EMPTY_DETAIL = MappingProxyType({})


@dataclass(slots=True)
class SkillData:
    """Immutable skill definition loaded from the compiled catalog."""

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


SkillRef = SkillData


def _stats_tuple(stats: dict[int, int] | tuple[int, ...] | list[int]) -> tuple[int, int, int, int, int, int]:
    if isinstance(stats, dict):
        keys = {
            Stats.HP: "hp",
            Stats.ATK_PHYS: "atk_phys",
            Stats.ATK_MAG: "atk_mag",
            Stats.DEF_PHYS: "def_phys",
            Stats.DEF_MAG: "def_mag",
            Stats.SPEED: "speed",
        }
        return tuple(int(stats.get(s, stats.get(keys[s], 0))) for s in Stats)  # type: ignore[return-value]
    values = tuple(int(v) for v in stats)
    if len(values) != len(Stats):
        raise ValueError(f"stats must contain {len(Stats)} values")
    return values  # type: ignore[return-value]


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


@dataclass(slots=True)
class PersistentPet:
    """Persistent team-slot Pet state shared across simulations."""

    name: str
    stats: dict[int, int] | tuple[int, int, int, int, int, int]
    types: tuple[str, str]
    moves: list[SkillData] | tuple[SkillData, ...]
    data_id: int = 0
    ability_id: int = 0
    ability_name: str = ""
    ability_desc: str = ""
    ability_effects: tuple[AbilityEffect, ...] = ()
    ability_tags: tuple[str, ...] = ()
    bloodline: str = ""
    nature: str = ""
    ivs: list[str] | tuple[str, ...] = ()

    def __post_init__(self) -> None:
        self.stats = _stats_tuple(self.stats)
        self.moves = tuple(self.moves)
        self.ability_effects = tuple(self.ability_effects)
        self.ability_tags = tuple(self.ability_tags)
        self.ivs = tuple(self.ivs)

    @classmethod
    def from_data(
        cls,
        data: PetData,
        moves: list[SkillData] | tuple[SkillData, ...],
        *,
        bloodline: str = "",
        nature: str = "",
        ivs: list[str] | tuple[str, ...] | None = None,
        ability_effects: tuple[AbilityEffect, ...] = (),
    ) -> "PersistentPet":
        return cls(
            name=data.name,
            stats=data.stats,
            types=data.types,
            moves=tuple(moves),
            data_id=data.pet_id,
            ability_id=data.ability_id,
            ability_name=data.ability_name,
            ability_desc=data.ability_desc,
            ability_effects=ability_effects,
            bloodline=bloodline,
            nature=nature,
            ivs=tuple(ivs or ()),
        )

    def add_ability_tag(self, tag: str) -> None:
        if tag and tag not in self.ability_tags:
            self.ability_tags = self.ability_tags + (tag,)

    def stat(self, stat: Stats) -> int:
        return self.stats[stat.value]  # type: ignore[index]


@dataclass(slots=True)
class ActivePet:
    """Battle-only mutable state, packed for the hot path."""

    persistent: PersistentPet
    current_hp: int = 0
    current_energy: int = 10
    buff_stages: int = _pack_buff()
    status_flags: int = StatusFlag.NONE
    status_counts: int = 0
    volt_flags: int = 0
    frostbite: int = 0
    cute: int = 0
    power_mult: int = 100
    charging_skill: int = -1
    cooldowns: int = 0
    leech_source: str = ""
    ability_flags: int = AbilityFlag.NONE
    ability_counters: int = 0
    burst_power_bonus: int = 40
    burst_extend: int = 0
    burst_enemy_cost_up: int = 0
    burst_element_cost_reduce: str = ""
    extra_freeze_stacks: int = 0
    next_power_bonus: int = 0
    next_power_pct_bps: int = 0
    is_fainted: bool = False
    slot: int = 0
    _power_mod: float = 1.0
    _defense_reduction: float = 0.0
    _cost_mod: int = 0
    _cost_mod_turns: int = 0

    @property
    def max_hp(self) -> int:
        return self.persistent.stat(Stats.HP) or 1

    @property
    def speed(self) -> int:
        return self._stat(Stats.SPEED)

    @property
    def hp_pct(self) -> float:
        return self.current_hp / max(1, self.max_hp)

    def _stat(self, stat: Stats) -> int:
        base = self.persistent.stat(stat)
        idx = {
            Stats.ATK_PHYS: 0,
            Stats.DEF_PHYS: 1,
            Stats.SPEED: 2,
            Stats.ATK_MAG: 3,
            Stats.DEF_MAG: 4,
        }.get(stat, 0)
        return int(base * buff_multiplier(_unpack_buff(self.buff_stages, idx)))

    @property
    def atk_phys(self) -> int:
        return self._stat(Stats.ATK_PHYS)

    @property
    def atk_mag(self) -> int:
        return self._stat(Stats.ATK_MAG)

    @property
    def def_phys(self) -> int:
        return self._stat(Stats.DEF_PHYS)

    @property
    def def_mag(self) -> int:
        return self._stat(Stats.DEF_MAG)

    @property
    def elements(self) -> tuple[str, ...]:
        primary, secondary = self.persistent.types
        return (primary, secondary) if secondary else (primary,)

    def set_buff(self, idx: int, val: int) -> None:
        self.buff_stages = _set_buff(self.buff_stages, idx, val)

    def get_buff(self, idx: int) -> int:
        return _unpack_buff(self.buff_stages, idx)

    def get_status_count(self, status: StatusType) -> int:
        return _unpack_status(self.status_counts, status)

    def set_status_count(self, status: StatusType, val: int) -> None:
        self.status_counts = _set_status(self.status_counts, status, val)

    def has_status(self, flag: StatusFlag) -> bool:
        return bool(self.status_flags & flag)

    def has_ability_flag(self, flag: AbilityFlag) -> bool:
        return bool(self.ability_flags & flag)

    def set_ability_flag(self, flag: AbilityFlag, enabled: bool = True) -> None:
        if enabled:
            self.ability_flags |= flag
        else:
            self.ability_flags &= ~flag

    def is_immune_to(self, flag: StatusFlag) -> bool:
        immunity = {"火": StatusFlag.BURN, "草": StatusFlag.LEECH, "毒": StatusFlag.POISON, "冰": StatusFlag.FREEZE}
        return any(immunity.get(elem) == flag for elem in self.elements)

    def reset_volatile(self) -> None:
        """Reset battle-only switch-out state."""

        self.buff_stages = _pack_buff()
        self.volt_flags = 0
        self.power_mult = 100
        self.charging_skill = -1
        self._power_mod = 1.0
        self._defense_reduction = 0.0
        self._cost_mod = 0
        self._cost_mod_turns = 0
        self.next_power_bonus = 0
        self.next_power_pct_bps = 0

    def clear_switch_status(self) -> None:
        """Clear NRC_AI-style volatile statuses that do not survive switch-out."""

        for status in (StatusType.BURN, StatusType.POISON, StatusType.LEECH):
            self.set_status_count(status, 0)
            self.status_flags &= ~status.flag
        self.leech_source = ""


@dataclass(slots=True)
class BattleEvent:
    turn: int
    actor: str
    action: str
    detail: MappingProxyType[str, Any] | dict[str, Any] = EMPTY_DETAIL


@dataclass(slots=True)
class MoveDecision:
    action: str
    skill_index: int | None = None
    switch_slot: int | None = None


@dataclass(slots=True)
class BattleState:
    team_a: tuple[ActivePet, ...] | list[ActivePet]
    team_b: tuple[ActivePet, ...] | list[ActivePet]
    active_a: int = 0
    active_b: int = 0
    magic_a: int = 4
    magic_b: int = 4
    weather: int = 0
    marks_a: int = 0
    marks_b: int = 0
    devotion_a: int = 0
    devotion_b: int = 0
    burst_entry_turn_a: int = 0
    burst_entry_turn_b: int = 0
    skill_counts_a: int = 0
    skill_counts_b: int = 0
    barrel_pending_a: bool = False
    barrel_pending_b: bool = False
    counter_count_a: int = 0
    counter_count_b: int = 0
    switch_this_turn_a: bool = False
    switch_this_turn_b: bool = False
    turn_number: int = 0
    log: tuple[BattleEvent, ...] = ()
    last_action_order: tuple[str, ...] = ()
    winner: str | None = None

    def __post_init__(self) -> None:
        self.team_a = tuple(self.team_a)
        self.team_b = tuple(self.team_b)
        self.log = tuple(self.log)
        self.last_action_order = tuple(self.last_action_order)

    @property
    def weather_type(self) -> WeatherType:
        return WeatherType(self.weather & 0xF)

    @weather_type.setter
    def weather_type(self, weather: WeatherType) -> None:
        self.weather = (self.weather & ~0xF) | (weather.value & 0xF)

    @property
    def weather_turns(self) -> int:
        return (self.weather >> 4) & 0xF

    @weather_turns.setter
    def weather_turns(self, turns: int) -> None:
        self.weather = (self.weather & 0xF) | ((turns & 0xF) << 4)


def record_event(state: BattleState, event: BattleEvent) -> None:
    """Append a debug event outside the packed simulation fields."""

    state.log = state.log + (event,)
