"""Core game constants — energy, damage, IV, weather, counter, marks."""

# ── Energy ──────────────────────────────────────────────────────
ENERGY_GAIN_PER_TURN: int = 2
STARTING_ENERGY: int = 10
MAX_ENERGY: int = 10

# ── Stat modifiers ──────────────────────────────────────────────
NATURE_BOOST: float = 0.10
NATURE_REDUCE: float = 0.10
IV_BONUS: float = 0.10

# ── Damage ──────────────────────────────────────────────────────
DAMAGE_FORMULA_CONSTANT: float = 0.9
STAB_MULTIPLIER: float = 1.5
BURN_HP_CAP: int = 1000
BURN_DAMAGE_PCT: float = 0.02
POISON_DAMAGE_PCT: float = 0.03
MIN_DAMAGE: int = 1
DEFAULT_MAX_TURNS: int = 200

# ── Weather ─────────────────────────────────────────────────────
WEATHER_DOT_FRACTION: float = 1.0 / 16.0
WEATHER_DOT_IMMUNE_TYPES: tuple[str, ...] = ("地", "机械")

# ── Counter ─────────────────────────────────────────────────────
COUNTER_DAMAGE_BONUS: float = 1.3
