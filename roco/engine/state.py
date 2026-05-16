"""pkmn-inspired data model — two-tier (Persistent/Battle) + packed bitfields."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntFlag, IntEnum, auto

# ── Enums ───────────────────────────────────────────────────────


class EffectFlag(IntFlag):
    NONE = 0; DRAIN = auto(); HEAL_HP = auto(); HEAL_ENERGY = auto()
    STEAL_ENERGY = auto(); DEFENSE = auto(); BURN = auto(); POISON = auto()
    FREEZE = auto(); LEECH = auto(); STAT_CHANGE = auto(); FORCE_SWITCH = auto()
    CHARGE = auto(); ENERGY_ALL_IN = auto(); WEATHER = auto(); COUNTER = auto()
    CONDITIONAL = auto(); MIRROR_DAMAGE = auto(); ENEMY_COST_UP = auto()
    HP_FOR_ENERGY = auto(); PERMANENT_MOD = auto(); PURE_DAMAGE = auto()
    BURST = auto(); AGILITY = auto(); IS_MARK = auto()


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
            "光": cls.LIGHT, "地": cls.GROUND, "地面": cls.GROUND, "岩": cls.GROUND,
            "冰": cls.ICE, "龙": cls.DRAGON, "电": cls.ELECTRIC, "毒": cls.POISON,
            "虫": cls.BUG, "武": cls.FIGHTING, "格斗": cls.FIGHTING,
            "翼": cls.FLYING, "飞行": cls.FLYING, "萌": cls.CUTE,
            "幽": cls.GHOST, "幽灵": cls.GHOST, "恶": cls.DARK,
            "机械": cls.MECHANICAL, "钢": cls.MECHANICAL,
            "幻": cls.ILLUSION, "超能": cls.ILLUSION,
        }
        return _m.get(s.replace("系", "").strip(), cls.NORMAL)


# ── Packed buff stage helpers ─────────────────────────────────

def _pack_buff(atk_p=0, atk_m=0, def_p=0, def_m=0, spd=4, acc=0, eva=0) -> int:
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
class SkillData:
    """Immutable skill definition — loaded from DB, never modified."""
    name: str; element: str; category: SkillCategory
    energy: int; power: int; effect: str
    effect_flags: int = EffectFlag.NONE
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


@dataclass(slots=True)
class PersistentPokemon:
    """Immutable pet definition — loaded from DB, shared across simulations."""
    name: str
    stats: dict[int, int]     # Stats enum → value
    types: tuple[str, str]    # (primary, secondary)
    moves: list[SkillData]
    ability_name: str = ""
    ability_desc: str = ""
    ability_tags: list[str] = field(default_factory=list)
    bloodline: str = ""
    nature: str = ""
    ivs: list[str] = field(default_factory=list)


@dataclass
class ActivePokemon:
    """Battle-only mutable state — reset on every switch-in."""
    persistent: PersistentPokemon
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
    ability_state: dict = field(default_factory=dict)
    is_fainted: bool = False
    slot: int = 0
    # Runtime scratch
    _power_mod: float = 1.0
    _defense_reduction: float = 0.0
    _cost_mod: int = 0
    _cost_mod_turns: int = 0

    @property
    def max_hp(self) -> int: return self.persistent.stats.get(Stats.HP, 1)
    @property
    def speed(self) -> int: return self.persistent.stats.get(Stats.SPEED, 0)
    @property
    def hp_pct(self) -> float: return self.current_hp / max(1, self.max_hp)

    def _stat(self, s: Stats) -> int:
        base = self.persistent.stats.get(s, 0)
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
    team_a: list[ActivePokemon]
    team_b: list[ActivePokemon]
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
