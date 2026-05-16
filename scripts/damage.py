"""Pure, stateless damage calculation engine for Roco Kingdom PVP.

All functions take explicit arguments and return computed results.
No randomness — every calculation is deterministic.

Uses type_chart.py for type effectiveness (additive: 单克2x, 双克3x).
"""

from __future__ import annotations

from scripts.battle_config import (
    BURN_HP_CAP,
    BURN_DAMAGE_PCT,
    POISON_DAMAGE_PCT,
    ENERGY_GAIN_PER_TURN,
    MAX_ENERGY,
    NATURE_BOOST,
    NATURE_REDUCE,
    IV_BONUS,
    IV_STAT_MAP,
    MIN_DAMAGE,
    NATURE_MOD,
    DAMAGE_FORMULA_CONSTANT,
    STAB_MULTIPLIER,
)
from scripts.systems.weather import weather_damage_mult
from scripts.type_chart import effectiveness_v2


# ── Stat computation ───────────────────────────────────────────

_NON_HP_STATS = ("atk_phys", "atk_mag", "def_phys", "def_mag", "speed")


def compute_stats(
    hp: int,
    atk_phys: int,
    atk_mag: int,
    def_phys: int,
    def_mag: int,
    speed: int,
    nature: str = "",
    ivs: list[str] | None = None,
) -> dict[str, int]:
    """Compute effective stats with nature (+10%/-10%) and IV focus (+10% each).

    IVs are applied first, then nature. Floor after each step.
    """
    stats: dict[str, int] = {
        "hp": hp,
        "atk_phys": atk_phys,
        "atk_mag": atk_mag,
        "def_phys": def_phys,
        "def_mag": def_mag,
        "speed": speed,
    }

    if ivs:
        stats = apply_iv_mod(stats, ivs)
    if nature:
        stats = apply_nature_mod(stats, nature)

    return stats


def apply_iv_mod(stats: dict[str, int], ivs: list[str]) -> dict[str, int]:
    """Apply +10% to each IV-focused stat. Non-HP stats only."""
    result = dict(stats)
    for iv_name in ivs:
        key = IV_STAT_MAP.get(iv_name)
        if key and key in _NON_HP_STATS:
            result[key] = int(result[key] * (1.0 + IV_BONUS))
    return result


def apply_nature_mod(stats: dict[str, int], nature: str) -> dict[str, int]:
    """Apply nature boost (+10%) and reduction (-10%). Neutral natures pass through."""
    pair = NATURE_MOD.get(nature)
    if not pair or (not pair[0] and not pair[1]):
        return dict(stats)

    result = dict(stats)
    boost_key, reduce_key = pair
    if boost_key and boost_key in _NON_HP_STATS:
        result[boost_key] = int(result[boost_key] * (1.0 + NATURE_BOOST))
    if reduce_key and reduce_key in _NON_HP_STATS:
        result[reduce_key] = int(result[reduce_key] * (1.0 - NATURE_REDUCE))
    return result


# ── Damage formulas ────────────────────────────────────────────


def calc_attack_damage(
    power: int,
    atk_stat: float,
    def_stat: float,
    type_mult: float = 1.0,
    stab: float = 1.0,
    weather_mult: float = 1.0,
    hit_count: int = 1,
    power_buff: float = 1.0,
) -> int:
    """Full attack damage formula matching game mechanics.

    damage = (atk / def) * power * 0.9 * type_mult * stab * weather * hits * power_buff
    Minimum MIN_DAMAGE if power > 0.
    """
    if power <= 0 or atk_stat <= 0 or def_stat <= 0:
        return 0
    base = (atk_stat / def_stat) * power * DAMAGE_FORMULA_CONSTANT
    total = base * type_mult * stab * weather_mult * hit_count * power_buff
    dmg = int(total)
    return max(dmg, MIN_DAMAGE)


def get_stab(move_element: str, pet_element: str) -> float:
    """Same-type attack bonus: 1.5x if move element matches pet element."""
    return STAB_MULTIPLIER if move_element == pet_element else 1.0


def get_weather_mult(move_element: str, weather: str | None) -> float:
    """Weather damage modifier for the given move element."""
    return weather_damage_mult(move_element, weather)


def calc_burn_damage(
    max_hp: int,
    stacks: int,
    type_mult: float = 1.0,
    mid_turn: bool = False,
) -> int:
    """Burn: min(max_hp, 1000) * stacks * 2% * type_mult.
    mid_turn=true forces type_mult=1.0 (true damage).
    """
    if stacks <= 0:
        return 0
    effective_hp = min(max_hp, BURN_HP_CAP)
    mult = 1.0 if mid_turn else type_mult
    return int(effective_hp * stacks * BURN_DAMAGE_PCT * mult)


def calc_burn_decay(stacks: int) -> int:
    """Burn stacks halve at end of turn, rounded up: ceil(stacks / 2)."""
    return (stacks + 1) // 2


def calc_poison_damage(max_hp: int, stacks: int) -> int:
    """Poison: 3% max HP per stack."""
    if stacks <= 0:
        return 0
    return int(max_hp * stacks * POISON_DAMAGE_PCT)


# ── Type multiplier ────────────────────────────────────────────


def get_type_multiplier(
    move_element: str,
    defender_types: tuple[str, ...],
) -> float:
    """Get type effectiveness multiplier for a move vs defender types.

    Uses type_chart.effectiveness_v2() which implements additive logic.
    """
    return effectiveness_v2(move_element, defender_types)


# ── Energy ─────────────────────────────────────────────────────


def can_use_skill(current_energy: int, skill_energy: int) -> bool:
    """Check if pet has enough energy to use a skill."""
    return current_energy >= skill_energy


def calc_energy_after_gain(current: int) -> int:
    """Add turn energy, capped at MAX_ENERGY."""
    return min(current + ENERGY_GAIN_PER_TURN, MAX_ENERGY)


def calc_energy_after_use(current: int, cost: int) -> int:
    """Deduct energy after using a skill. Min 0."""
    return max(current - cost, 0)


# ── Buff stages ────────────────────────────────────────────────


def buff_multiplier(stage: int) -> float:
    """Buff stage to multiplier. +6 = 1.6x, -6 = 0.625x."""
    if stage >= 0:
        return 1.0 + stage * 0.10
    else:
        return 1.0 / (1.0 + abs(stage) * 0.10)


def clamp_stage(stage: int) -> int:
    """Clamp buff/debuff stage to [-6, 6]."""
    return max(-6, min(6, stage))


def apply_buff_stages(
    stats: dict[str, int], stages: dict[str, int]
) -> dict[str, int]:
    """Apply buff/debuff multipliers to effective stats."""
    result = dict(stats)
    for key in _NON_HP_STATS:
        if key in stages:
            result[key] = int(result[key] * buff_multiplier(stages[key]))
    return result
