"""Engine-inspired Pet data model: two-tier runtime state plus packed bitfields."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntFlag, IntEnum, auto
from types import MappingProxyType
from typing import Any

# ── Enums ───────────────────────────────────────────────────────


class EffectFlag(IntFlag):
    NONE = 0; DRAIN = auto(); HEAL_HP = auto(); HEAL_ENERGY = auto()
    STEAL_ENERGY = auto(); DEFENSE = auto(); BURN = auto(); POISON = auto()
    FREEZE = auto(); LEECH = auto(); STAT_CHANGE = auto(); FORCE_SWITCH = auto()
    CHARGE = auto(); ENERGY_ALL_IN = auto(); WEATHER = auto(); COUNTER = auto()
    CONDITIONAL = auto(); MIRROR_DAMAGE = auto(); ENEMY_COST_UP = auto()
    HP_FOR_ENERGY = auto(); PERMANENT_MOD = auto(); PURE_DAMAGE = auto()
    BURST = auto(); AGILITY = auto(); IS_MARK = auto()


class Timing(IntEnum):
    """NRC_AI-style effect trigger points, stored as compact integer codes."""
    PASSIVE = 0
    BATTLE_START = 1
    TURN_START = 2
    BEFORE_MOVE = 3
    ON_DAMAGE = 4
    AFTER_MOVE = 5
    TURN_END = 6
    SWITCH_IN = 7
    SWITCH_OUT = 8
    FAINT = 9
    KILL = 10
    COUNTER_SUCCESS = 11


class EffectTag(IntEnum):
    """Effect primitive codes used by skill and ability effect rows."""
    DAMAGE = 1
    HEAL_HP = 2
    HEAL_ENERGY = 3
    STEAL_ENERGY = 4
    ENEMY_LOSE_ENERGY = 5
    LIFE_DRAIN = 6
    SELF_BUFF = 7
    ENEMY_DEBUFF = 8
    BURN = 9
    POISON = 10
    FREEZE = 11
    LEECH = 12
    METEOR = 13
    MARK = 14
    DAMAGE_REDUCTION = 15
    FORCE_SWITCH = 16
    ENERGY_ALL_IN = 17
    WEATHER = 18
    COUNTER_ATTACK = 19
    COUNTER_STATUS = 20
    COUNTER_DEFENSE = 21
    BARREL_STATE = 22
    BURST_POWER_BONUS = 23
    FAINT_NO_MP_LOSS = 24
    ENERGY_REGEN_PER_TURN = 25


class AbilityFlag(IntFlag):
    """Packed runtime ability flags. Parameterized bonuses use fixed fields."""
    NONE = 0
    BARREL_ACTIVE = auto()
    REVIVE = auto()
    FAKE_DEATH = auto()
    COST_INVERT = auto()
    ENERGY_NO_CAP = auto()


class StatusFlag(IntFlag):
    NONE = 0; BURN = auto(); POISON = auto(); FREEZE = auto(); LEECH = auto()


class StatusType(IntEnum):
    BURN = 0; POISON = 1; FREEZE = 2; LEECH = 3
    @property
    def flag(self) -> StatusFlag: return StatusFlag(1 << self.value)


class SkillCategory(IntEnum):
    PHYSICAL = 1; MAGICAL = 2; DEFENSE = 3; STATUS = 4


class Stats(IntEnum):
    HP = 0; ATK_PHYS = 1; ATK_MAG = 2; DEF_PHYS = 3; DEF_MAG = 4; SPEED = 5


class WeatherType(IntEnum):
    NONE = 0; RAIN = 1; SANDSTORM = 2; SNOW = 3


class Element(IntEnum):
    """Roco 18-element system for per-element skill count packing."""
    NORMAL = 0; GRASS = 1; FIRE = 2; WATER = 3; LIGHT = 4; GROUND = 5
    ICE = 6; DRAGON = 7; ELECTRIC = 8; POISON = 9; BUG = 10; FIGHTING = 11
    FLYING = 12; CUTE = 13; GHOST = 14; DARK = 15; MECHANICAL = 16; ILLUSION = 17

    @classmethod
    def from_str(cls, s: str) -> "Element":
        _m = {
            "普通": cls.NORMAL, "草": cls.GRASS, "火": cls.FIRE, "水": cls.WATER,
            "光": cls.LIGHT, "地": cls.GROUND, "地面": cls.GROUND,
            "冰": cls.ICE, "龙": cls.DRAGON, "电": cls.ELECTRIC, "毒": cls.POISON,
            "虫": cls.BUG, "武": cls.FIGHTING, "格斗": cls.FIGHTING,
            "翼": cls.FLYING, "飞行": cls.FLYING, "萌": cls.CUTE,
            "幽": cls.GHOST, "幽灵": cls.GHOST, "恶": cls.DARK,
            "机械": cls.MECHANICAL,
            "幻": cls.ILLUSION, "超能": cls.ILLUSION,
        }
        token = s.replace("系", "").strip()
        if token in {"岩", "岩石", "钢", "Rock", "ROCK", "rock", "Steel", "STEEL", "steel"}:
            raise ValueError(f"legacy element is not supported: {s!r}")
        try:
            return _m[token]
        except KeyError as exc:
            raise ValueError(f"unknown element: {s!r}") from exc


ELEMENT_NAMES: tuple[str, ...] = (
    "普通", "草", "火", "水", "光", "地", "冰", "龙", "电",
    "毒", "虫", "武", "翼", "萌", "幽", "恶", "机械", "幻",
)


def normalize_element_name(value: str) -> str:
    """Normalize structured element input to the canonical Roco Chinese name."""
    return ELEMENT_NAMES[Element.from_str(value).value]


# ── Packed buff stage helpers ─────────────────────────────────

def _pack_buff(atk_p=0, atk_m=0, def_p=0, def_m=0, spd=0, acc=0, eva=0) -> int:
    """Pack 7 buff stages into u32. Each 4 bits, signed (-6 to +6)."""
    def s(v): return (v + 6) & 0xF
    return (s(atk_p) | s(def_p) << 4 | s(spd) << 8 | s(atk_m) << 12 |
            s(def_m) << 16 | s(acc) << 20 | s(eva) << 24)


def _unpack_buff(packed: int, idx: int) -> int:
    """Unpack one buff stage (signed). idx 0=atk_phys,1=def_phys,2=speed,3=atk_mag,4=def_mag,5=acc,6=eva."""
    return ((packed >> (idx * 4)) & 0xF) - 6


def _set_buff(packed: int, idx: int, val: int) -> int:
    clamped = max(-6, min(6, val))
    shift = idx * 4
    packed &= ~(0xF << shift)
    return packed | ((clamped + 6) & 0xF) << shift


def buff_multiplier(stage: int) -> float:
    """Buff stage → multiplier. +6=1.6, -6=0.625."""
    return 1.0 + stage * 0.10 if stage >= 0 else 1.0 / (1.0 + abs(stage) * 0.10)


# ── Packed status counts ──────────────────────────────────────

def _pack_status(burn=0, poison=0, freeze=0, leech=0) -> int:
    return (burn & 0xFF) | (poison & 0xFF) << 8 | (freeze & 0xFF) << 16 | (leech & 0xFF) << 24


def _unpack_status(packed: int, t: StatusType) -> int:
    return (packed >> (t.value * 8)) & 0xFF


def _set_status(packed: int, t: StatusType, val: int) -> int:
    shift = t.value * 8
    packed &= ~(0xFF << shift)
    return packed | ((val & 0xFF) << shift)


# ── Mark/Devotion pack ────────────────────────────────────────

class MarkIdx(IntEnum):
    MOISTURE=0; DRAGON=1; CHARGE=2; WIND=3; ELECTRIC=4; SOLAR=5; ATTACK=6
    SLOW=7; SPIRIT=8; METEOR=9; POISON=10; THORN=11

class DevotionIdx(IntEnum):
    JIAMEI=0; FEIDUAN=1; CHONGJIAN=2; KUNFU=3; CHONGQUN=4

def _pack_marks(**counts) -> int:
    r = 0
    for k, v in counts.items():
        r |= (v & 0xF) << (k.value * 4)
    return r

def _unpack_mark(packed: int, idx: MarkIdx) -> int:
    return (packed >> (idx.value * 4)) & 0xF

def _set_mark(packed: int, idx: MarkIdx, val: int) -> int:
    shift = idx.value * 4
    return (packed & ~(0xF << shift)) | ((val & 0xF) << shift)

def _pack_devotion(**counts) -> int:
    r = 0
    for k, v in counts.items():
        r |= (v & 0xF) << (k.value * 4)
    return r

def _unpack_devotion(packed: int, idx: DevotionIdx) -> int:
    return (packed >> (idx.value * 4)) & 0xF

# ── Skill count pack ───────────────────────────────────────────

def _pack_skill_counts(**counts: int) -> int:
    """Pack per-element skill usage counts. 18 elements × 4bits each = 72 bits."""
    r = 0
    for elem, cnt in counts.items():
        r |= (cnt & 0xF) << (elem.value * 4)
    return r

def _unpack_skill_count(packed: int, elem: Element) -> int:
    return (packed >> (elem.value * 4)) & 0xF

def _inc_skill_count(packed: int, elem: Element) -> int:
    shift = elem.value * 4
    cur = (packed >> shift) & 0xF
    if cur < 0xF:
        return (packed & ~(0xF << shift)) | ((cur + 1) << shift)
    return packed

# ── Weather pack ───────────────────────────────────────────────

def _pack_weather(wtype: WeatherType, turns: int) -> int:
    return (wtype.value & 0xF) | (turns & 0xF) << 4


def _unpack_weather(packed: int) -> tuple[WeatherType, int]:
    return WeatherType(packed & 0xF), (packed >> 4) & 0xF


# ── Burst entry turn pack ──────────────────────────────────────

def _pack_burst_entries(**slots) -> int:
    """Pack 6 slots × 6bits each (turn 0-63). Key = slot index 0-5."""
    r = 0
    for slot, turn in slots.items():
        r |= (turn & 0x3F) << (slot * 6)
    return r


def _unpack_burst_entry(packed: int, slot: int) -> int:
    """Get entry turn for a slot (0-5). Returns 0 if never entered."""
    return (packed >> (slot * 6)) & 0x3F

def _set_burst_entry(packed: int, slot: int, turn: int) -> int:
    """Set entry turn for a slot (0-5)."""
    shift = slot * 6
    return (packed & ~(0x3F << shift)) | ((turn & 0x3F) << shift)


# ── Cooldown pack ─────────────────────────────────────────────

def _pack_cooldown(cds: dict[int, int]) -> int:
    r = 0
    for idx, cd in cds.items():
        if 0 <= idx < 8 and cd > 0:
            r |= (min(cd, 15) & 0xF) << (idx * 4)
    return r


def _unpack_cooldown(packed: int) -> dict[int, int]:
    return {i: v for i in range(8) if (v := (packed >> (i * 4)) & 0xF) > 0}


# ── Dataclasses ────────────────────────────────────────────────


@dataclass(slots=True)
class EffectSpec:
    """Compiled effect primitive from data storage."""
    tag: EffectTag
    timing: Timing
    params: MappingProxyType[str, Any] = field(default_factory=lambda: MappingProxyType({}))
    chance: float = 1.0
    condition: str = ""


@dataclass(slots=True)
class SkillEffect:
    skill_id: int
    effect: EffectSpec
    sort_order: int = 0


@dataclass(slots=True)
class AbilityEffect:
    ability_id: int
    effect: EffectSpec
    sort_order: int = 0


@dataclass(slots=True)
class SkillData:
    """Immutable skill definition — loaded from DB, never modified."""
    name: str; element: str; category: SkillCategory
    energy: int; power: int; effect: str
    skill_id: int = 0
    element_id: int = 0
    effect_flags: int = EffectFlag.NONE
    effects: tuple[SkillEffect, ...] = ()
    # Pre-parsed effect values
    life_drain: float = 0; self_heal_hp: float = 0; self_heal_energy: int = 0
    steal_energy: int = 0; enemy_lose_energy: int = 0
    damage_reduction: float = 0; hit_count: int = 1
    force_switch: bool = False; priority_mod: int = 0
    burn_stacks: int = 0; poison_stacks: int = 0; freeze_stacks: int = 0
    leech_stacks: int = 0; meteor_stacks: int = 0
    self_atk: float = 0; self_spatk: float = 0; self_def: float = 0; self_spdef: float = 0; self_speed: float = 0
    enemy_atk: float = 0; enemy_def: float = 0; enemy_spatk: float = 0; enemy_spdef: float = 0; enemy_speed: float = 0
    weather_type: str = ""; enemy_cost_up_amount: int = 0; hp_cost_pct: float = 0
    permanent_hit_growth: int = 0; permanent_power_growth: int = 0
    burst: bool = False; agility: bool = False; is_mark: bool = False; devotion_affected: bool = False; charge: bool = False
    # Counter effects
    counter_physical_drain: float = 0; counter_physical_energy_drain: int = 0
    counter_physical_self_atk: float = 0; counter_defense_enemy_def: float = 0
    counter_status_burn_stacks: int = 0; counter_status_poison_stacks: int = 0
    counter_status_freeze_stacks: int = 0; counter_damage_reflect: float = 0


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
    types: tuple[str, str]    # (primary, secondary)
    moves: list[SkillData] | tuple[SkillData, ...]
    data_id: int = 0
    ability_id: int = 0
    ability_name: str = ""
    ability_desc: str = ""
    ability_tags: list[str] = field(default_factory=list)
    bloodline: str = ""
    nature: str = ""
    ivs: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.stats = _stats_tuple(self.stats)
        self.moves = tuple(self.moves)

    @classmethod
    def from_data(
        cls,
        data: PetData,
        moves: list[SkillData] | tuple[SkillData, ...],
        *,
        bloodline: str = "",
        nature: str = "",
        ivs: list[str] | None = None,
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
            bloodline=bloodline,
            nature=nature,
            ivs=ivs or [],
        )

    def stat(self, stat: Stats) -> int:
        return self.stats[stat.value]  # type: ignore[index]


@dataclass
class ActivePet:
    """Battle-only mutable state — reset on every switch-in."""
    persistent: PersistentPet
    current_hp: int = 0
    current_energy: int = 10
    buff_stages: int = _pack_buff()   # packed u32
    status_flags: int = StatusFlag.NONE
    status_counts: int = 0            # packed u32
    volt_flags: int = 0               # temporary volatile effects
    frostbite: int = 0; cute: int = 0
    power_mult: int = 100             # fixed-point ×100 (1.0 = 100)
    charging_skill: int = -1
    cooldowns: int = 0               # packed
    leech_source: str = ""
    ability_flags: int = AbilityFlag.NONE
    ability_counters: int = 0
    burst_power_bonus: int = 40
    burst_extend: int = 0
    burst_enemy_cost_up: int = 0
    burst_element_cost_reduce: str = ""
    is_fainted: bool = False
    slot: int = 0
    # Runtime scratch
    _power_mod: float = 1.0
    _defense_reduction: float = 0.0
    _cost_mod: int = 0
    _cost_mod_turns: int = 0

    @property
    def max_hp(self) -> int: return self.persistent.stat(Stats.HP) or 1
    @property
    def speed(self) -> int: return self._stat(Stats.SPEED)
    @property
    def hp_pct(self) -> float: return self.current_hp / max(1, self.max_hp)

    def _stat(self, s: Stats) -> int:
        base = self.persistent.stat(s)
        idx = {Stats.ATK_PHYS:0, Stats.DEF_PHYS:1, Stats.SPEED:2, Stats.ATK_MAG:3, Stats.DEF_MAG:4}.get(s, 0)
        stage = _unpack_buff(self.buff_stages, idx)
        return int(base * buff_multiplier(stage))

    @property
    def atk_phys(self) -> int: return self._stat(Stats.ATK_PHYS)
    @property
    def atk_mag(self) -> int: return self._stat(Stats.ATK_MAG)
    @property
    def def_phys(self) -> int: return self._stat(Stats.DEF_PHYS)
    @property
    def def_mag(self) -> int: return self._stat(Stats.DEF_MAG)

    @property
    def elements(self) -> tuple[str, ...]:
        t = self.persistent.types
        return (t[0], t[1]) if t[1] else (t[0],)

    def set_buff(self, idx: int, val: int) -> None:
        self.buff_stages = _set_buff(self.buff_stages, idx, val)

    def get_buff(self, idx: int) -> int:
        return _unpack_buff(self.buff_stages, idx)

    def get_status_count(self, t: StatusType) -> int:
        return _unpack_status(self.status_counts, t)

    def set_status_count(self, t: StatusType, val: int) -> None:
        self.status_counts = _set_status(self.status_counts, t, val)

    def has_status(self, f: StatusFlag) -> bool:
        return bool(self.status_flags & f)

    def has_ability_flag(self, f: AbilityFlag) -> bool:
        return bool(self.ability_flags & f)

    def set_ability_flag(self, f: AbilityFlag, enabled: bool = True) -> None:
        if enabled:
            self.ability_flags |= f
        else:
            self.ability_flags &= ~f

    def is_immune_to(self, f: StatusFlag) -> bool:
        IMMUNITY = {"火": StatusFlag.BURN, "草": StatusFlag.LEECH, "毒": StatusFlag.POISON, "冰": StatusFlag.FREEZE}
        for elem in self.elements:
            if IMMUNITY.get(elem) == f:
                return True
        return False

    def reset_volatile(self) -> None:
        """Reset battle-only state (called on switch-out)."""
        self.buff_stages = _pack_buff()
        self.volt_flags = 0
        self.power_mult = 100
        self.charging_skill = -1
        self._power_mod = 1.0
        self._defense_reduction = 0.0
        self._cost_mod = 0
        self._cost_mod_turns = 0


@dataclass
class BattleEvent:
    turn: int; actor: str; action: str
    detail: dict = field(default_factory=dict)


@dataclass
class MoveDecision:
    action: str
    skill_index: int | None = None
    switch_slot: int | None = None


@dataclass
class BattleState:
    team_a: list[ActivePet]
    team_b: list[ActivePet]
    active_a: int = 0; active_b: int = 0
    magic_a: int = 4; magic_b: int = 4
    weather: int = 0               # packed weather: type(4)|turns(4)
    marks_a: int = 0       # packed: 12 marks × 4bits (counts)
    marks_b: int = 0
    devotion_a: int = 0    # packed: 5 devotions × 4bits (counts)
    devotion_b: int = 0
    burst_entry_turn_a: int = 0  # packed: 6 slots × 6bits
    burst_entry_turn_b: int = 0
    skill_counts_a: int = 0  # packed: 18 elements × 4bits
    skill_counts_b: int = 0
    barrel_pending_a: bool = False; barrel_pending_b: bool = False
    counter_count_a: int = 0; counter_count_b: int = 0
    switch_this_turn_a: bool = False; switch_this_turn_b: bool = False
    turn_number: int = 0
    log: list[BattleEvent] = field(default_factory=list)
    winner: str | None = None

    @property
    def weather_type(self) -> WeatherType: return WeatherType(self.weather & 0xF)
    @weather_type.setter
    def weather_type(self, w: WeatherType) -> None:
        self.weather = (self.weather & ~0xF) | (w.value & 0xF)
    @property
    def weather_turns(self) -> int: return (self.weather >> 4) & 0xF
    @weather_turns.setter
    def weather_turns(self, t: int) -> None:
        self.weather = (self.weather & 0xF) | ((t & 0xF) << 4)
