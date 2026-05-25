"""Combat flow primitives: counters, interrupts, hit counts, switches, cost mods."""

from __future__ import annotations

from roco.engine.kernel.catalog import SKILL_FLAG_CHARGE
from roco.engine.kernel.ctx import StageCtx
from roco.engine.kernel.op_rows import (
    ROW_ARG0,
    ROW_ARG1,
    ROW_ARG2,
    ROW_ARG3,
    ROW_TARGET,
    ROW_TIMING,
    TARGET_SELF,
    TIMING_HOOK_BEFORE_MOVE,
    TIMING_PAK_ROUND_CALC_START,
)


# ── counters / interrupts ────────────────────────────────────────────────

def op_counter_attack(ctx: StageCtx, row: tuple[int, ...]) -> None:
    ctx.counter_damage += row[ROW_ARG0]


def op_install_counter(ctx: StageCtx, row: tuple[int, ...]) -> None:
    """Install a pak counter-trigger response skill on the actor.

    Backs the pak "应对！X" family (1031041..1031117 …): pak's
    ``effect_param[0]`` is the 70xxxxx response skill_id, which this op
    stashes in ``ctx.actor_counter_install_skill_id``.  ``apply_after_move``
    folds it into ``SideState.counter_skill_id``, and ``mechanics`` fires
    the looked-up counter skill on the next incoming hit
    (``TIMING_PAK_ROUND_END``), then clears the slot.
    """
    skill_id = row[ROW_ARG0]
    if skill_id > 0:
        ctx.actor_counter_install_skill_id = skill_id


def op_interrupt(ctx: StageCtx, row: tuple[int, ...]) -> None:
    ctx.interrupt = 1


def op_on_interrupt_cooldown(ctx: StageCtx, row: tuple[int, ...]) -> None:
    if ctx.interrupt:
        ctx.enemy_cooldown_turns = max(ctx.enemy_cooldown_turns, row[ROW_ARG0])


def op_counter_success_speed_priority(ctx: StageCtx, row: tuple[int, ...]) -> None:
    if ctx.counter_success:
        ctx.priority_next += row[ROW_ARG0]


def op_priority_next_delta(ctx: StageCtx, row: tuple[int, ...]) -> None:
    """Unconditional priority boost for the actor's next turn.

    Backs pak's "迅捷" family (1051001 …): a TURN_END payload that grants
    +N priority next turn.  ``apply_after_move`` already folds
    ``ctx.priority_next`` into the actor's ``priority_boost`` lane.
    """
    if row[ROW_ARG0] > 0:
        ctx.priority_next += row[ROW_ARG0]


def op_counter_accumulate_transform(ctx: StageCtx, row: tuple[int, ...]) -> None:
    if not ctx.counter_success:
        return
    required_category = row[ROW_ARG1]
    if required_category and ctx.counter_category != required_category:
        return
    if ctx.actor_counter_count >= row[ROW_ARG0]:
        ctx.form_transform = 1
        ctx.form_transform_heal = row[ROW_ARG2]


# ── hit count adjustments ────────────────────────────────────────────────

def op_hit_count_delta(ctx: StageCtx, row: tuple[int, ...]) -> None:
    if not _skill_filter_matches(ctx, row):
        return
    if row[ROW_TARGET] == TARGET_SELF:
        if row[ROW_TIMING] in (TIMING_HOOK_BEFORE_MOVE, TIMING_PAK_ROUND_CALC_START):
            ctx.hit_count += row[ROW_ARG0]
        else:
            ctx.actor_hit_delta += row[ROW_ARG0]
    else:
        ctx.enemy_hit_delta += row[ROW_ARG0]


def op_hit_count_percent_delta(ctx: StageCtx, row: tuple[int, ...]) -> None:
    if row[ROW_TARGET] == TARGET_SELF:
        ctx.hit_count += ctx.hit_count * row[ROW_ARG0] // 100


def op_hit_count_by_team_skill_count(ctx: StageCtx, row: tuple[int, ...]) -> None:
    skill_id = row[ROW_ARG1]
    if skill_id and ctx.skill_id != skill_id:
        return
    ctx.hit_count += ctx.side_same_skill_count * row[ROW_ARG0]


def op_first_strike_hit_count(ctx: StageCtx, row: tuple[int, ...]) -> None:
    if ctx.first_strike:
        ctx.hit_count += row[ROW_ARG0]


def op_hit_count_per_poison(ctx: StageCtx, row: tuple[int, ...]) -> None:
    ctx.hit_count += ctx.target_poison_stacks * row[ROW_ARG0]


def op_hit_count_per_poison_effect(ctx: StageCtx, row: tuple[int, ...]) -> None:
    ctx.hit_count += ctx.target_poison_effect_stacks * row[ROW_ARG0]


def op_stat_scale_hits_per_hp_lost(ctx: StageCtx, row: tuple[int, ...]) -> None:
    ctx.hit_count += ctx.actor_hp_lost_quarters * row[ROW_ARG0]


def op_on_skill_element_hit_count(ctx: StageCtx, row: tuple[int, ...]) -> None:
    if ctx.skill_element == row[ROW_ARG0]:
        ctx.hit_count += row[ROW_ARG1]


def _skill_filter_matches(ctx: StageCtx, row: tuple[int, ...]) -> bool:
    skill_ids = (row[ROW_ARG1], row[ROW_ARG2], row[ROW_ARG3])
    return not any(skill_ids) or ctx.skill_id in skill_ids


# ── forced switches ──────────────────────────────────────────────────────

def op_force_switch(ctx: StageCtx, row: tuple[int, ...]) -> None:
    ctx.force_switch = 1


def op_force_enemy_switch(ctx: StageCtx, row: tuple[int, ...]) -> None:
    ctx.force_enemy_switch = 1


def op_auto_switch_on_zero_energy(ctx: StageCtx, row: tuple[int, ...]) -> None:
    if ctx.actor_energy <= 0:
        ctx.force_switch = 1


# ── cooldowns ────────────────────────────────────────────────────────────

def op_set_self_cooldown(ctx: StageCtx, row: tuple[int, ...]) -> None:
    """Lock the actor's currently-used skill slot for ``row[ROW_ARG0]`` turns.

    Backs pak's "公共冷却" effects (1037001/1037002) attached to defensive
    skills (防御 / 有效预防 / 风墙 / …).  ``apply_after_move`` reads
    ``ctx.actor_self_cooldown_turns`` together with ``ctx.skill_slot``
    to write the cooldown into the actor's packed slot.
    """
    turns = row[ROW_ARG0]
    if turns > 0 and ctx.skill_slot >= 0:
        ctx.actor_self_cooldown_turns = max(ctx.actor_self_cooldown_turns, turns)


# ── energy / cost mods ───────────────────────────────────────────────────

def op_charge_cost_reduce(ctx: StageCtx, row: tuple[int, ...]) -> None:
    if ctx.skill_flags & SKILL_FLAG_CHARGE:
        ctx.cost_delta -= row[ROW_ARG0]


def op_energy_drain_by_cost_diff(ctx: StageCtx, row: tuple[int, ...]) -> None:
    diff = ctx.skill_energy - ctx.target_skill_energy
    if diff > 0:
        ctx.enemy_lose_energy += diff


# ── devotion / blood lines ───────────────────────────────────────────────

def op_devotion_grant_random(ctx: StageCtx, row: tuple[int, ...]) -> None:
    ctx.devotion_random += row[ROW_ARG0]
