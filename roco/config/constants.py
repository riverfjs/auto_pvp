"""Outer-layer constants and compatibility aliases.

Kernel rule constants live in :mod:`roco.engine.common.rules`.
"""

from roco.engine.common import rules

# ── Energy ──────────────────────────────────────────────────────
STARTING_ENERGY: int = rules.STARTING_ENERGY
MAX_ENERGY: int = rules.MAX_ENERGY
FOCUS_ENERGY_GAIN: int = rules.FOCUS_ENERGY_GAIN

# ── Stat modifiers ──────────────────────────────────────────────
NATURE_BOOST: float = 0.10
NATURE_REDUCE: float = 0.10
IV_BONUS: float = 0.10

# ── Damage ──────────────────────────────────────────────────────
DAMAGE_FORMULA_CONSTANT: float = rules.DAMAGE_CONST_BPS / rules.BPS
STAB_MULTIPLIER: float = rules.STAB_BPS / rules.BPS
BURN_HP_CAP: int = rules.BURN_HP_CAP
BURN_DAMAGE_PCT: float = rules.BURN_DAMAGE_BPS / rules.BPS
POISON_DAMAGE_PCT: float = rules.POISON_DAMAGE_BPS / rules.BPS
MIN_DAMAGE: int = rules.MIN_DAMAGE
DEFAULT_MAX_TURNS: int = 200

# ── Weather ─────────────────────────────────────────────────────
WEATHER_DOT_FRACTION: float = 1.0 / rules.SANDSTORM_DAMAGE_DENOM
WEATHER_DOT_IMMUNE_TYPES: tuple[str, ...] = ("地", "机械")

# ── Counter ─────────────────────────────────────────────────────
COUNTER_DAMAGE_BONUS: float = 1.3
