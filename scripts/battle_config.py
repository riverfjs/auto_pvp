"""Tunable constants for the battle simulator. No behavior — just data."""

# ── Energy system ──────────────────────────────────────────────
ENERGY_GAIN_PER_TURN: int = 2
STARTING_ENERGY: int = 10      # pets enter battle at full energy
MAX_ENERGY: int = 10           # energy cap

# ── Stat modifiers ─────────────────────────────────────────────
NATURE_BOOST: float = 0.10
NATURE_REDUCE: float = 0.10
IV_BONUS: float = 0.10

# ── Damage ─────────────────────────────────────────────────────
BURN_HP_CAP: int = 1000
BURN_DAMAGE_PCT: float = 0.02
POISON_DAMAGE_PCT: float = 0.03
MIN_DAMAGE: int = 1
DEFAULT_MAX_TURNS: int = 200

# ── Nature → (boost_stat, reduce_stat) ────────────────────────
# Stat keys: atk_phys, atk_mag, def_phys, def_mag, speed
# Empty strings = neutral nature
NATURE_MOD: dict[str, tuple[str, str]] = {
    "固执": ("atk_phys", "atk_mag"),
    "开朗": ("speed", "atk_mag"),
    "胆小": ("speed", "atk_phys"),
    "保守": ("atk_mag", "atk_phys"),
    "沉默": ("atk_mag", "speed"),
    "淘气": ("def_phys", "atk_mag"),
    "稳重": ("def_mag", "atk_phys"),
    "急躁": ("speed", "def_phys"),
    "勇敢": ("atk_phys", "speed"),
    "大胆": ("def_phys", "atk_phys"),
    "悠闲": ("def_phys", "speed"),
    "慎重": ("def_mag", "atk_mag"),
    "马虎": ("atk_mag", "def_mag"),
    "天真": ("speed", "def_mag"),
    "冷静": ("atk_mag", "speed"),
    "狂妄": ("def_mag", "speed"),
    "沉着": ("def_mag", "atk_phys"),
    "调皮": ("atk_phys", "def_mag"),
    "孤僻": ("atk_phys", "def_phys"),
    "温和": ("def_mag", "atk_phys"),
    "温顺": ("def_mag", "def_phys"),
    "浮躁": ("", ""),
    "害羞": ("", ""),
    "认真": ("", ""),
    "平和": ("", ""),
    "实干": ("", ""),
}

# ── IV stat name → pet stat key ────────────────────────────────
IV_STAT_MAP: dict[str, str] = {
    "生命": "hp",
    "物攻": "atk_phys",
    "魔攻": "atk_mag",
    "物防": "def_phys",
    "魔防": "def_mag",
    "速度": "speed",
}

# ── Status effects ─────────────────────────────────────────────
STATUS_ELEMENT_IMMUNITY: dict[str, str] = {
    "火": "灼烧",
    "草": "寄生",
    "毒": "中毒",
    "冰": "冻结",
}

# ── Damage formula ─────────────────────────────────────────────
DAMAGE_FORMULA_CONSTANT: float = 0.9   # multiplier applied to base damage
STAB_MULTIPLIER: float = 1.5            # same-type attack bonus
ENERGY_CAP: int = 10                    # max energy
STARTING_ENERGY_FULL: int = 10          # energy when entering battle

# ── Weather ────────────────────────────────────────────────────
# Weather → {element → damage_multiplier}
WEATHER_DAMAGE_MULT: dict[str, dict[str, float]] = {
    "rain": {"水": 1.5},
    "sandstorm": {},
    "snow": {},
}
# End-of-turn weather damage: sandstorm hits non-地/钢/机械 for 1/16 HP
WEATHER_DOT_FRACTION: float = 1.0 / 16.0
WEATHER_DOT_IMMUNE_TYPES: tuple[str, ...] = ("地", "钢", "机械")

# ── Counter system (应对) ──────────────────────────────────────
# Defense skills counter physical attacks; Status counters defense;
# Physical/Magical counters status attacks.
# When a counter succeeds, the counter-er activates bonus effects.
COUNTER_MATRIX: dict[str, str] = {
    "防御": "物攻",   # 防御应对物攻
    "状态": "防御",   # 状态应对防御
    "物攻": "状态",   # 物攻应对状态
    "魔攻": "状态",   # 魔攻应对状态
}
# When counter succeeds: bonus damage multiplier on counter-move
COUNTER_DAMAGE_BONUS: float = 1.3

# ── Mark system (印记) ─────────────────────────────────────────
# Team-wide persistent buffs stored in marks_a / marks_b dicts.
# Key mark types and their effects:

# 正面印记 (positive marks)
MARK_POSITIVE: set[str] = {
    "moisture_mark",   # 湿润印记: 全队技能能耗-1
    "dragon_mark",     # 龙噬印记: 3能量技能攻击+30%
    "charge_mark",     # 蓄势印记: 攻击威力+30%, 能耗+1
    "wind_mark",       # 风起印记: 先手攻击威力+20%
    "electric_mark",   # 蓄电印记: 入场首回合威力+10/层
    "solar_mark",      # 光合印记: 回合结束回能+层数
    "attack_mark",     # 攻击印记: 全技能威力+10%/层
}

# 负面印记 (negative marks)
MARK_NEGATIVE: set[str] = {
    "slow_mark",       # 减速印记: 速度-10
    "spirit_mark",     # 降灵印记: 入场时失去能量
    "meteor_mark",     # 星陨印记: 非幻系攻击触发幻系额外伤害
    "poison_mark",     # 中毒印记: 回合结束3%×层数毒伤
    "thorn_mark",      # 棘刺印记: 入场失去6%×层数HP
}
# Mark tick amounts
MARK_POISON_DMG_PCT: float = 0.03   # 中毒印记每层伤害
MARK_SOLAR_ENERGY: int = 1          # 光合印记每层回能
MARK_SPIRIT_ENERGY_LOSS: int = 1    # 降灵印记入场失能
MARK_THORN_HP_PCT: float = 0.06     # 棘刺印记入场HP损失
MARK_SLOW_SPEED_REDUCE: int = 10    # 减速印记速度减少
MARK_MOISTURE_COST_REDUCE: int = 1  # 湿润印记能耗降低
MARK_METEOR_EXTRA_DMG_PER_STACK: int = 30  # 星陨每层额外魔伤

# ── Counter system ─────────────────────────────────────────────
# When attacker uses skill of type A and defender uses skill of type B:
# If A is countered by B (based on COUNTER_MATRIX), B "应对成功" and gains bonuses.
# This models the 洛克王国 应对/反击 mechanic.
