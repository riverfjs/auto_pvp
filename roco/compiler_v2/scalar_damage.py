"""Pure scalar helpers shared by data tests and the fixed kernel."""

from __future__ import annotations

from roco.common.constants import (
    BPS, DAMAGE_CONST_BPS, STAB_BPS, MIN_DAMAGE,
    BURN_HP_CAP, BURN_DAMAGE_BPS, POISON_DAMAGE_BPS,
    FOCUS_ENERGY_GAIN, MAX_ENERGY, IV_BONUS,
    TYPE_DOUBLE_RESIST_BPS, TYPE_DOUBLE_WEAK_BPS, TYPE_NEUTRAL_BPS,
)
from roco.common.enums import Element
from roco.generated.type_chart import TYPE_CHART_BPS

DAMAGE_FORMULA_CONSTANT = DAMAGE_CONST_BPS / BPS
STAB_MULTIPLIER = STAB_BPS / BPS
BURN_DAMAGE_PCT = BURN_DAMAGE_BPS / BPS
POISON_DAMAGE_PCT = POISON_DAMAGE_BPS / BPS
from roco.common.natures import IV_STAT_MAP, NATURE_EFFECTS_BY_NAME
from roco.common.packing import buff_multiplier as _bm


def _effectiveness_bps(move_element: str, defender_types: tuple[str, ...]) -> int:
    """Float-API wrapper around the pak-derived BPS chart.

    Mirrors :func:`roco.engine.kernel.damage.type_bps` in plain Python so
    test / display callers don't need the kernel chain.  Returns the
    final BPS multiplier (10000 = 1.0×).
    """
    types: list[int] = []
    for t in defender_types:
        if not t or t == "无":
            continue
        try:
            types.append(Element.from_str(t).value)
        except ValueError:
            continue
    if not types:
        return TYPE_NEUTRAL_BPS
    try:
        move_id = Element.from_str(move_element).value
    except ValueError:
        return TYPE_NEUTRAL_BPS
    first = TYPE_CHART_BPS[move_id][types[0]]
    if len(types) == 1:
        return first
    second = TYPE_CHART_BPS[move_id][types[1]]
    if first > BPS and second > BPS:
        return TYPE_DOUBLE_WEAK_BPS
    if first < BPS and second < BPS:
        return TYPE_DOUBLE_RESIST_BPS
    if (first > BPS and second < BPS) or (first < BPS and second > BPS):
        # Weak + resist on opposite types cancel; matches kernel's
        # ``damage.type_bps`` rule so the compiler/preview path stays in
        # lockstep with the runtime.
        return TYPE_NEUTRAL_BPS
    # Otherwise exactly one side is neutral — fall through to the
    # non-neutral one (or to neutral when both are).
    return first if first != BPS else second


def can_use_skill(current_energy: int, cost: int) -> bool:
    return current_energy >= cost

def energy_after_gain(current: int) -> int:
    return min(current + FOCUS_ENERGY_GAIN, MAX_ENERGY)

def energy_after_use(current: int, cost: int) -> int:
    return max(current - cost, 0)


def apply_iv_mod(stats: dict[str, int], ivs: list[str] | None = None) -> dict[str, int]:
    """Apply simple +10% IV bonuses to selected non-HP battle stats."""
    result = dict(stats)
    for iv in ivs or []:
        key = IV_STAT_MAP.get(iv)
        if not key or key == "hp" or key not in result:
            continue
        result[key] = int(result[key] * (1.0 + IV_BONUS))
    return result


def apply_nature_mod(stats: dict[str, int], nature: str = "") -> dict[str, int]:
    """Apply pak-derived nature boost/reduction."""
    result = dict(stats)
    effect = NATURE_EFFECTS_BY_NAME.get(nature)
    if effect is None:
        return result
    boost, boost_bps, reduce, reduce_bps = effect
    if boost and boost in result:
        result[boost] = result[boost] * (BPS + boost_bps) // BPS
    if reduce and reduce in result:
        result[reduce] = result[reduce] * (BPS - reduce_bps) // BPS
    return result


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
    """Build battle stats from base values, applying IV before nature."""
    stats = {
        "hp": hp,
        "atk_phys": atk_phys,
        "atk_mag": atk_mag,
        "def_phys": def_phys,
        "def_mag": def_mag,
        "speed": speed,
    }
    return apply_nature_mod(apply_iv_mod(stats, ivs), nature)


def calc_attack_damage(
    power: int, atk: float, dfn: float, type_mult: float = 1.0,
    stab: float = 1.0, weather: float = 1.0, hit_count: int = 1,
    power_buff: float = 1.0,
) -> int:
    if power <= 0 or atk <= 0 or dfn <= 1:
        return 0
    base = (atk / dfn) * power * DAMAGE_FORMULA_CONSTANT
    return max(MIN_DAMAGE, int(base * type_mult * stab * weather * hit_count * power_buff))


def get_stab(move_element: str, pet_element: str) -> float:
    return STAB_MULTIPLIER if move_element == pet_element else 1.0

def get_type_multiplier(move_element: str, defender_types: tuple[str, ...]) -> float:
    return _effectiveness_bps(move_element, defender_types) / BPS

def calc_burn_damage(max_hp: int, stacks: int, type_mult: float = 1.0, mid_turn: bool = False) -> int:
    if stacks <= 0: return 0
    hp = min(max_hp, BURN_HP_CAP)
    m = 1.0 if mid_turn else type_mult
    return int(hp * stacks * BURN_DAMAGE_PCT * m)

def burn_decay(stacks: int) -> int:
    if stacks <= 0:
        return 0
    return max(0, stacks - max(1, stacks // 2))
calc_burn_decay = burn_decay

def calc_poison_damage(max_hp: int, stacks: int) -> int:
    return int(max_hp * stacks * POISON_DAMAGE_PCT) if stacks > 0 else 0

def clamp_stage(v: int) -> int: return max(-6, min(6, v))
def buff_multiplier(stage: int) -> float: return _bm(stage)

calc_energy_after_gain = energy_after_gain
calc_energy_after_use = energy_after_use


def apply_buff_stages(stats: dict[str, int], stages: dict[str, int]) -> dict[str, int]:
    """Apply battle buff stages to non-HP stats."""
    result = dict(stats)
    for key, stage in stages.items():
        if key == "hp" or key not in result:
            continue
        result[key] = int(result[key] * buff_multiplier(clamp_stage(stage)))
    return result
