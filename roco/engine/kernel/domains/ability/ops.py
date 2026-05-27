"""Ability-domain runtime ops."""

from __future__ import annotations

from roco.common.constants import BPS
from roco.common.enums import SkillCategory
from roco.engine.kernel.core.ctx import StageCtx
from roco.engine.kernel.core.rows import ROW_ARG0, ROW_ARG1


def op_life_trick_power_hp_cost(ctx: StageCtx, row: tuple[int, ...]) -> None:
    """生命戏法: attack skills gain power, then pay current HP after resolution."""
    if ctx.skill_category not in (SkillCategory.PHYSICAL.value, SkillCategory.MAGICAL.value):
        return
    ctx.power_bps = ctx.power_bps * (BPS + row[ROW_ARG0]) // BPS
    ctx.self_current_hp_damage_bps = max(ctx.self_current_hp_damage_bps, row[ROW_ARG1])


def op_burn_decay_growth_marker(ctx: StageCtx, row: tuple[int, ...]) -> None:
    """Catalog marker for ability-flag-backed burn decay growth.

    This op is intentionally not linked for 煤渣草; the pak shape is represented
    by an ability flag so it is active while the pet is on field instead of only
    after the ability row has executed.
    """
    del ctx, row
