"""Game-rule constants consumed by kernel, compiler, and data layers.

Pak-derivable values are auto-generated to roco/generated/pak_rules.py
and re-exported here for a single import surface. Everything else in this file is a game-design value (damage formula,
status DOT rate, mark stack value, PVP format rule) not present in pak as a
named constant and must be curated manually.
"""

from __future__ import annotations

# Pak-derived constants (regenerate with: uv run python -m roco.compiler.gen_prefix_map)
from roco.generated.pak_rules import (  # noqa: F401
    DAMAGE_PERCENT_LIMIT,
    PVP_LEVEL,
    SKILL_DAMAGE_MAX,
    TYPE_DOUBLE_WEAK_BPS,
    TYPE_NEUTRAL_BPS,
    TYPE_RESIST_BPS,
    TYPE_WEAK_BPS,
)

# ── Numeric convention ─────────────────────────────────────────────────────
BPS = 10_000

# ── Energy ─────────────────────────────────────────────────────────────────
STARTING_ENERGY = 10
MAX_ENERGY = 10
FOCUS_ENERGY_GAIN = 5
HP_FOR_ENERGY_PCT_BPS = 500

# ── PVP format ─────────────────────────────────────────────────────────────
SIDE_LIVES = 4
WILLPOWER_USES = 2
LEADER_USES = 1
MAGIC_WILLPOWER = 1
MAGIC_LEADER_TRANSFORM = 2
WILLPOWER_POWER = 80
WILLPOWER_COUNTER_STATUS_BPS = 15_000
BLOODLINE_LEADER = 18
BLOODLINE_POLLUTANT = 19
DEFAULT_MAX_TURNS = 200

# ── Damage formula ─────────────────────────────────────────────────────────
DAMAGE_CONST_BPS = 9_000
STAB_BPS = 15_000
MIN_DAMAGE = 1
RAIN_WATER_BPS = 15_000
# Kernel uses 1/3 for "both defender types resist" (multiplicative composite).
# Not the same semantic as pak's `triple_restrained_percent`.
TYPE_DOUBLE_RESIST_BPS = 3_333

# ── Stat formula (nature / IV) ─────────────────────────────────────────────
NATURE_BOOST = 0.10
NATURE_REDUCE = 0.10
IV_BONUS = 0.10
COUNTER_DAMAGE_BONUS = 1.3

# ── Residual / status DOT ─────────────────────────────────────────────────
BURN_HP_CAP = 1_000
BURN_DAMAGE_BPS = 200
POISON_DAMAGE_BPS = 300
LEECH_DAMAGE_BPS = 800
SANDSTORM_DAMAGE_DENOM = 16
SNOW_FREEZE_STACKS = 2

# ── Mark values ────────────────────────────────────────────────────────────
SLOW_SPEED_REDUCE = 10
MOISTURE_COST_REDUCE = 1
MOMENTUM_COST_UP = 1
METEOR_POWER = 30
THORN_ENTRY_DAMAGE_BPS = 600
SPIRIT_ENTRY_ENERGY_LOSS = 1
MARK_ATTACK_BPS = 1_000
MARK_WIND_BPS = 2_000
MARK_SLUGGISH_BPS = 3_000
MARK_MOMENTUM_BPS = 3_000
MARK_DRAGON_BPS = 4_000

# ── Cute ───────────────────────────────────────────────────────────────────
CUTE_DAMAGE_BPS_PER_STACK = 500
CUTE_MAX_STACKS = 15
CUTE_LETHAL_SHIELD_COST = 5
