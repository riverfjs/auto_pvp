"""Mark (印记) system — team-wide persistent buffs/debuffs.

Marks live on BattleState.marks_a / marks_b and persist across switches.
Each side can have at most 1 positive mark and 1 negative mark at a time.

Positive marks: moisture, dragon, charge, wind, electric, solar, attack
Negative marks: slow, spirit, meteor, poison, thorn
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from scripts.battle import PetState

# ── Mark definitions ───────────────────────────────────────────

POSITIVE_MARKS = frozenset({
    "moisture",   # 湿润: 全队技能能耗-1/层
    "dragon",     # 龙噬: 3能技能攻击+30%/层
    "charge",     # 蓄势: 攻击威力+30%, 能耗+1
    "wind",       # 风起: 先手攻击威力+20%/层
    "electric",   # 蓄电: 入场首回合威力+10/层 (迸发)
    "solar",      # 光合: 回合结束回能+1/层
    "attack",     # 攻击: 全技能威力+10%/层
})

NEGATIVE_MARKS = frozenset({
    "slow",       # 减速: 速度-10/层
    "spirit",     # 降灵: 入场时失去1能量/层
    "meteor",     # 星陨: 非幻系攻击触发幻系额外魔伤
    "poison",     # 中毒: 回合结束3%HP毒伤/层
    "thorn",      # 棘刺: 入场失去6%HP/层
})

# ── Mark tick values ───────────────────────────────────────────

POISON_DMG_PCT = 0.03     # 中毒印记每层伤害 (max HP %)
THORN_HP_PCT = 0.06       # 棘刺入场HP损失 (max HP %)
SPIRIT_ENERGY_LOSS = 1    # 降灵入场失能/层
SOLAR_ENERGY = 1          # 光合回合结束回能/层
SLOW_SPEED_REDUCE = 10    # 减速速度减少/层
MOISTURE_COST_REDUCE = 1  # 湿润能耗降低/层
METEOR_EXTRA_DMG = 30     # 星陨每层额外幻系魔伤

# ── Mark lifecycle functions ───────────────────────────────────

def apply_marks_to_speed(speed: int, marks: dict[str, float]) -> int:
    """Slow mark reduces speed."""
    stacks = int(marks.get("slow", 0))
    return max(1, speed - stacks * SLOW_SPEED_REDUCE)


def apply_marks_to_skill_cost(cost: int, marks: dict[str, float]) -> int:
    """Moisture mark reduces skill energy cost."""
    stacks = int(marks.get("moisture", 0))
    return max(0, cost - stacks * MOISTURE_COST_REDUCE)


def apply_marks_to_attack_power(
    power: int,
    skill_element: str,
    marks: dict[str, float],
    atk_element: str,
) -> float:
    """Apply mark-based power multipliers. Returns multiplier >= 1.0."""
    mult = 1.0

    # 攻击印记: +10%/层
    attack_stacks = int(marks.get("attack", 0))
    if attack_stacks > 0:
        mult += attack_stacks * 0.10

    # 蓄势印记: +30% but +1 energy cost (cost handled separately)
    charge_stacks = int(marks.get("charge", 0))
    if charge_stacks > 0:
        mult += charge_stacks * 0.30

    return mult


def apply_marks_on_enter(pet: "PetState", marks: dict[str, float]) -> tuple[int, int]:
    """Apply mark effects when a pet enters battle.
    Returns (hp_loss, energy_loss).
    """
    hp_loss = 0
    energy_loss = 0

    # 棘刺印记
    thorn_stacks = int(marks.get("thorn", 0))
    if thorn_stacks > 0:
        hp_loss = int(pet.max_hp * thorn_stacks * THORN_HP_PCT)

    # 降灵印记
    spirit_stacks = int(marks.get("spirit", 0))
    if spirit_stacks > 0:
        energy_loss = spirit_stacks * SPIRIT_ENERGY_LOSS

    return hp_loss, energy_loss


def tick_marks_end_of_turn(
    pet: "PetState", marks: dict[str, float]
) -> tuple[int, int]:
    """Process end-of-turn mark effects on a pet.
    Returns (hp_loss, energy_gain).
    """
    hp_loss = 0
    energy_gain = 0

    # 中毒印记: 3%HP毒伤/层
    poison_stacks = int(marks.get("poison", 0))
    if poison_stacks > 0 and pet.current_hp > 0:
        hp_loss += int(pet.max_hp * poison_stacks * POISON_DMG_PCT)

    # 光合印记: 回能/层
    solar_stacks = int(marks.get("solar", 0))
    if solar_stacks > 0:
        energy_gain += solar_stacks * SOLAR_ENERGY

    return hp_loss, energy_gain


def calc_meteor_extra_damage(marks: dict[str, float]) -> int:
    """星陨印记额外幻系魔伤 = 层数 * 30. Stacks are consumed after hit."""
    stacks = int(marks.get("meteor", 0))
    if stacks <= 0:
        return 0
    return stacks * METEOR_EXTRA_DMG
