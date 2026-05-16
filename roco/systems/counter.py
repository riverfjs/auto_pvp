"""Counter (应对) system — rock-paper-scissors style move interaction.

When two moves resolve in the same turn, the move category determines
if a counter occurs:
  - 防御 (defense) counters 物攻 (physical) and 魔攻 (magical)
  - 状态 (status) counters 防御 (defense)
  - 物攻/魔攻 counter 状态 (status)

A successful counter gives: +30% damage to the countering move.
"""

from roco.engine.state import SkillCategory

COUNTERS: dict[SkillCategory, SkillCategory] = {
    SkillCategory.DEFENSE: SkillCategory.PHYSICAL,
    SkillCategory.STATUS: SkillCategory.DEFENSE,
    SkillCategory.PHYSICAL: SkillCategory.STATUS,
    SkillCategory.MAGICAL: SkillCategory.STATUS,
}

COUNTER_DAMAGE_BONUS = 1.3


def get_counter_target(category: SkillCategory) -> SkillCategory | None:
    return COUNTERS.get(category)


def is_counter(category_a: SkillCategory, category_b: SkillCategory) -> bool:
    return COUNTERS.get(category_a) == category_b


def resolve_counter(
    cat_a: SkillCategory, cat_b: SkillCategory
) -> tuple[bool, bool]:
    return is_counter(cat_a, cat_b), is_counter(cat_b, cat_a)
