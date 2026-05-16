"""Counter (应对) system — rock-paper-scissors style move interaction.

When two moves resolve in the same turn, the move category determines
if a counter occurs:
  - 防御 (defense) counters 物攻 (physical) and 魔攻 (magical)
  - 状态 (status) counters 防御 (defense)
  - 物攻/魔攻 counter 状态 (status)

A successful counter gives: +30% damage to the countering move.
"""

# ── Counter matrix ─────────────────────────────────────────────

# Key: counter-er category → Value: counter-ee category
COUNTERS: dict[str, str] = {
    "防御": "物攻",   # 防御应对攻击
    "状态": "防御",   # 状态应对防御
    "物攻": "状态",   # 攻击应对状态
    "魔攻": "状态",   # 攻击应对状态
}

COUNTER_DAMAGE_BONUS = 1.3


def get_counter_target(category: str) -> str | None:
    """Return the category that `category` counters, or None."""
    return COUNTERS.get(category)


def is_counter(category_a: str, category_b: str) -> bool:
    """Check if A counters B."""
    return COUNTERS.get(category_a) == category_b


def resolve_counter(
    cat_a: str, cat_b: str
) -> tuple[bool, bool]:
    """Resolve counter between two move categories.

    Returns (a_counters_b, b_counters_a).
    """
    return is_counter(cat_a, cat_b), is_counter(cat_b, cat_a)
