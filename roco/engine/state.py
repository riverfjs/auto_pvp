"""Battle state data classes — pure data, no behavior beyond properties."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntFlag, IntEnum, auto
from roco.config.constants import STARTING_ENERGY
from roco.config.status import STATUS_ELEMENT_IMMUNITY


# ── Bitfield enums ─────────────────────────────────────────────

class EffectFlag(IntFlag):
    """Skill effect flags — O(1) bitmask lookup, no string matching."""
    NONE = 0
    DRAIN = auto()          # 吸血
    HEAL_HP = auto()        # 回血
    HEAL_ENERGY = auto()    # 回能
    STEAL_ENERGY = auto()   # 偷能量
    DEFENSE = auto()        # 减伤
    BURN = auto()           # 灼烧
    POISON = auto()         # 中毒
    FREEZE = auto()         # 冻结
    LEECH = auto()          # 寄生
    STAT_CHANGE = auto()    # 属性变化
    FORCE_SWITCH = auto()   # 强制换人
    CHARGE = auto()         # 蓄力
    ENERGY_ALL_IN = auto()  # 全额投入
    WEATHER = auto()        # 天气设置
    COUNTER = auto()        # 应对效果
    CONDITIONAL = auto()    # 条件触发
    MIRROR_DAMAGE = auto()  # 镜反伤害
    ENEMY_COST_UP = auto()  # 敌方能耗+
    HP_FOR_ENERGY = auto()  # HP换能
    PERMANENT_MOD = auto()  # 永久修改
    PURE_DAMAGE = auto()    # 纯伤害
    BURST = auto()          # 迸发
    AGILITY = auto()        # 迅捷
    IS_MARK = auto()        # 印记技能


class StatusFlag(IntFlag):
    """Persistent status effects — bitmask on PetState."""
    NONE = 0
    BURN = auto()
    POISON = auto()
    FREEZE = auto()
    LEECH = auto()


class StatusType(IntEnum):
    """String-free status type keys for status_counts dict."""
    BURN = 1; POISON = 2; FREEZE = 3; LEECH = 4


class Stats(IntEnum):
    """String-free stat keys for buff_stages and effective_stats."""
    HP = 0; ATK_PHYS = 1; ATK_MAG = 2; DEF_PHYS = 3; DEF_MAG = 4; SPEED = 5


class SkillCategory(IntEnum):
    """String-free skill category."""
    PHYSICAL = 1   # 物攻
    MAGICAL = 2    # 魔攻
    DEFENSE = 3    # 防御
    STATUS = 4     # 状态


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
    effect_flags: int = EffectFlag.NONE  # bitmask replacing tags list
    # Pre-parsed effect values (set at import time, zero runtime regex)
    weather_type: str = ""           # "sandstorm"|"rain"|"snow"|""
    enemy_cost_up_amount: int = 0
    hp_cost_pct: float = 0.0
    permanent_hit_growth: int = 0
    permanent_power_growth: int = 0
    # Combined stat modifiers
    self_all_atk: float = 0      # 双攻+
    self_all_def: float = 0      # 双防+
    enemy_all_atk: float = 0     # 敌方双攻-
    enemy_all_def: float = 0     # 敌方双防-
    # Mechanic flags
    is_mark: bool = False        # 印记技能 (vs 临时buff)
    agility: bool = False        # 迅捷入场自动释放
    burst: bool = False          # 迸发技能
    devotion_affected: bool = False
    charge: bool = False           # 蓄力技能
    # Counter effects (triggered on COUNTER_SUCCESS)
    counter_physical_drain: float = 0
    counter_physical_energy_drain: int = 0
    counter_physical_self_atk: float = 0
    counter_physical_enemy_def: float = 0
    counter_defense_self_atk: float = 0
    counter_defense_self_def: float = 0
    counter_defense_enemy_def: float = 0
    counter_defense_enemy_energy_cost: int = 0
    counter_status_power_mult: float = 0
    counter_status_enemy_lose_energy: int = 0
    counter_status_poison_stacks: int = 0
    counter_status_burn_stacks: int = 0
    counter_status_freeze_stacks: int = 0
    counter_skill_cooldown: int = 0
    counter_damage_reflect: float = 0


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
    status_flags: int = StatusFlag.NONE   # bitmask for burn/poison/freeze/leech
    status_counts: dict[str, int] = field(default_factory=dict)  # stack counts
    frostbite_damage: int = 0
    power_multiplier: float = 1.0
    charging_skill_idx: int = -1
    cooldowns: dict[int, int] = field(default_factory=dict)
    is_fainted: bool = False
    leech_source: str = ""              # name of pet that applied leech
    slot: int = 0
    ability_name: str = ""
    ability_desc: str = ""
    ability_tags: list[str] = field(default_factory=list)
    ability_state: dict = field(default_factory=dict)    # runtime KV store
    meteor_countdown: int = 0
    meteor_stacks: int = 0
    cute_stacks: int = 0
    # Runtime modifiers (reset on switch-out)
    life_drain_mod: float = 0
    skill_power_bonus: int = 0
    skill_power_pct_mod: float = 0
    skill_cost_mod: int = 0
    hit_count_mod: int = 0
    priority_stage: int = 0
    next_attack_power_bonus: int = 0
    next_attack_power_pct: float = 0  # pre-classified

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

    def is_immune_to_status(self, flag: StatusFlag) -> bool:
        """Check if pet's element grants immunity to a status effect."""
        name = _STATUS_FLAG_TO_NAME.get(flag, "")
        if not name:
            return False
        for elem, sname in STATUS_ELEMENT_IMMUNITY.items():
            if sname == name and elem in self.defender_types:
                return True
        return False


_STATUS_FLAG_TO_NAME: dict[StatusFlag, str] = {
    StatusFlag.BURN: "灼烧", StatusFlag.POISON: "中毒",
    StatusFlag.FREEZE: "冻结", StatusFlag.LEECH: "寄生",
}


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
    # Subsystem state
    devotion_a: dict[str, int] = field(default_factory=dict)
    devotion_b: dict[str, int] = field(default_factory=dict)
    burst_entry_turn_a: dict[str, int] = field(default_factory=dict)
    burst_entry_turn_b: dict[str, int] = field(default_factory=dict)
    barrel_pending_a: bool = False
    barrel_pending_b: bool = False
    counter_count_a: int = 0
    counter_count_b: int = 0
    switch_this_turn_a: bool = False
    switch_this_turn_b: bool = False
    skill_use_counts_a: dict[str, int] = field(default_factory=dict)
    skill_use_counts_b: dict[str, int] = field(default_factory=dict)
    turn_number: int = 0
    log: list[BattleEvent] = field(default_factory=list)
    winner: str | None = None
