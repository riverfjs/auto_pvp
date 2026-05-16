"""Tunable constants for the battle simulator. No behavior — just data."""

# ── Energy system ──────────────────────────────────────────────
ENERGY_GAIN_PER_TURN: int = 2
STARTING_ENERGY: int = 0
MAX_ENERGY: int = 8

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
# Which element types grant immunity to which status
STATUS_ELEMENT_IMMUNITY: dict[str, str] = {
    "火": "灼烧",
    "草": "寄生",
    "毒": "中毒",
    "冰": "冻结",
}
