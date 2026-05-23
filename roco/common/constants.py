"""Game-rule constants consumed by kernel, compiler, and data layers.

Pak-derivable values are auto-generated to ``roco/generated/battle_globals.py``.
This module selects the specific keys the engine needs and re-exports them
beside hand-curated kernel policy.
"""

from __future__ import annotations

from roco.generated.battle_globals import BATTLE_GLOBAL_NUMS

# Pak-derived constants (regenerate with: uv run python -m roco.compiler_v2.gen_prefix_map).
TYPE_NEUTRAL_BPS = BATTLE_GLOBAL_NUMS["restraint_percent"]
TYPE_WEAK_BPS = BATTLE_GLOBAL_NUMS["double_restraint_percent"]
TYPE_DOUBLE_WEAK_BPS = BATTLE_GLOBAL_NUMS["triple_restraint_percent"]
TYPE_RESIST_BPS = BATTLE_GLOBAL_NUMS["restrained_percent"]
TYPE_DOUBLE_RESIST_BPS = BATTLE_GLOBAL_NUMS["double_restrained_percent"]
DAMAGE_PERCENT_LIMIT = BATTLE_GLOBAL_NUMS["damage_percent_limit"]
SKILL_DAMAGE_MAX = BATTLE_GLOBAL_NUMS["skill_damage_max"]
PVP_LEVEL = BATTLE_GLOBAL_NUMS["battle_pvp_level"]

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
# ``TYPE_DOUBLE_RESIST_BPS`` (both defender types resist) is now pulled
# from pak's ``double_restrained_percent`` via :mod:`battle_globals` (= 7500 BPS,
# 0.75×).  The previous hand-coded 3333 (1/3×) is replaced; if the game
# turns out to use a different composition rule a manual override would
# go here with a justification, not silently in source.

# ── Stat formula (IV; nature proportions are pak-generated) ────────────────
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
